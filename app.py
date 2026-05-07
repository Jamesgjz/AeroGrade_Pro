import streamlit as st
import pandas as pd
import requests
import json
import io
import zipfile
import PyPDF2
import streamlit.components.v1 as components
from groq import Groq
import google.generativeai as genai
import time

# 1. Configuración de Página
st.set_page_config(page_title="AeroGrade Pro - UNIMINUTO", layout="wide")

if 'estudiantes_evaluados' not in st.session_state:
    st.session_state['estudiantes_evaluados'] = []
if 'tokens_acumulados' not in st.session_state:
    st.session_state['tokens_acumulados'] = 0

# 2. Funciones de Inteligencia y Soporte
def listar_modelos_gemini(api_key):
    try:
        genai.configure(api_key=api_key)
        return [m.name.replace('models/', '') for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    except: return ["gemini-1.5-flash", "gemini-1.5-pro"]

def enviar_nota_canvas(domain, token, course_id, assignment_id, student_id, nota, comentario_html):
    url = f"{domain.rstrip('/')}/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/{student_id}"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"submission[posted_grade]": nota, "comment[text_comment]": comentario_html}
    try:
        response = requests.put(url, headers=headers, data=payload)
        return response.status_code == 200
    except: return False

# 3. Sidebar - Configuración de Motores
st.sidebar.header("⚙️ Configuración del Motor")
motor_ia = st.sidebar.selectbox("Seleccione Motor:", ["Groq (Gratis)", "Google Gemini (Potencia/Pago)"])

groq_key = st.secrets.get("GROQ_API_KEY", "")
gemini_key = ""
modelo_seleccionado = "llama-3.3-70b-versatile"

if motor_ia == "Google Gemini (Potencia/Pago)":
    gemini_key = st.sidebar.text_input("Ingrese Gemini API Key:", type="password")
    if gemini_key:
        opciones = listar_modelos_gemini(gemini_key)
        modelo_seleccionado = st.sidebar.selectbox("Versión de Gemini Detectada:", opciones)

canvas_token = st.sidebar.text_input("Canvas Token", type="password")
curso_id = st.sidebar.text_input('ID Curso', value='11731')
actividad_id = st.sidebar.text_input('ID Actividad', value='208144')

st.title("🛡️ AeroGrade Pro: Validación y Control Total")
st.markdown("---")

# 4. Parámetros de la Actividad
c_p1, c_p2 = st.columns(2)
with c_p1: st.session_state.enunciado = st.text_area("📝 Enunciado:", height=100)
with c_p2: st.session_state.plantilla = st.text_area("🖥️ Plantilla HTML:", height=100)

# 5. Carga de Insumos
st.subheader("📤 Carga de Archivos")
c1, c2, c3 = st.columns(3)
with c1: archivo_calificaciones = st.file_uploader("CSV Calificaciones", type=["csv"])
with c2: archivo_rubricas = st.file_uploader("CSV Rúbricas", type=["csv"])
with c3: archivo_zip = st.file_uploader('ZIP de Entregas', type=['zip'])

if archivo_calificaciones and archivo_rubricas:
    df_cal = pd.read_csv(archivo_calificaciones)
    df_rub = pd.read_csv(archivo_rubricas)
    columnas_act = [col for col in df_cal.columns if any(k in col for k in ['MA Evaluación', 'MT Evaluación', 'MT Evidencia'])]
    
    if columnas_act:
        actividad_sel = st.selectbox("🎯 ACTIVIDAD:", ["-- Seleccione --"] + columnas_act)
        
        if actividad_sel != "-- Seleccione --":
            rubrica_txt = df_rub[df_rub['Rubric Name'] == st.selectbox('Rúbrica:', df_rub['Rubric Name'].unique())].to_csv(index=False)
            df_final = df_cal[df_cal['Student'].astype(str).str.strip() != 'Points Possible'].copy()
            df_final = df_final[df_final['ID'].notna()]

            # --- MONITOR DE COSTOS (LO GANADO) ---
            st.markdown("### 📊 Monitor de Inversión")
            m1, m2, m3 = st.columns(3)
            m1.metric("Tokens Consumidos", f"{st.session_state['tokens_acumulados']:,}")
            if "Gemini" in motor_ia:
                costo_usd = (st.session_state['tokens_acumulados'] / 1_000_000) * 0.10
                m2.metric("Costo Est. (USD)", f"${costo_usd:.4f}")
                m3.metric("Motor", "Gemini")
            else:
                m2.metric("Costo Real", "$0.00")
                m3.metric("Motor", "Groq")

            # --- VISUALIZACIÓN PREVIA DE RESULTADOS ---
            if st.session_state['estudiantes_evaluados']:
                st.subheader("✅ Borradores para Validación")
                for e in st.session_state['estudiantes_evaluados']:
                    with st.expander(f"🧑‍🎓 {e['nombre']} - Nota: {e['nota']}", expanded=False):
                        components.html(e['html_final'], height=150, scrolling=True)

            st.divider()
            b_eval, b_reset = st.columns(2)
            with b_eval:
                btn_iniciar = st.button('🚀 INICIAR CALIFICACIÓN VISUAL', type="primary", use_container_width=True)
            with b_reset:
                if st.button("🧹 EMPEZAR DE CERO", use_container_width=True):
                    st.session_state['estudiantes_evaluados'] = []
                    st.session_state['tokens_acumulados'] = 0
                    st.rerun()

            if btn_iniciar:
                progreso = st.progress(0)
                status_box = st.empty()
                log_container = st.container()

                for idx, (i, row) in enumerate(df_final.iterrows()):
                    nombre = row.get('Student', 'Estudiante')
                    sid = str(int(float(row.get('ID', 0))))
                    nombre_busqueda = nombre.split(',')[0].lower().strip() # Tomamos el primer apellido
                    
                    if sid in [e['student_id'] for e in st.session_state['estudiantes_evaluados']]:
                        progreso.progress((idx + 1) / len(df_final))
                        continue
                    
                    status_box.info(f"🔍 Buscando entrega de: **{nombre}**")
                    
                    contenido = ""
                    if archivo_zip:
                        with zipfile.ZipFile(archivo_zip, 'r') as z:
                            # BÚSQUEDA HÍBRIDA: Primero por ID, luego por Apellido si falla
                            archivos = [f for f in z.namelist() if sid in f or nombre_busqueda in f.lower()]
                            
                            if archivos:
                                with log_container: st.info(f"📄 Leyendo: {archivos} para {nombre}")
                                for f_n in archivos:
                                    with z.open(f_n) as f:
                                        ext = f_n.lower()
                                        if any(ext.endswith(e) for e in ['.java', '.py', '.txt', '.sql', '.r', '.html', '.css', '.js', '.xml', '.pkt', '.docx']):
                                            contenido += f"\n--- {f_n} ---\n"
                                            contenido += f.read().decode('utf-8', errors='ignore')
                                        elif ext.endswith('.pdf'):
                                            reader = PyPDF2.PdfReader(io.BytesIO(f.read()))
                                            for p in reader.pages: contenido += p.extract_text()
                            else:
                                with log_container: st.warning(f"⚠️ Sin archivos para {nombre} (ID: {sid})")

                    if contenido:
                        try:
                            prompt = f"Profesor Uniminuto. Evalúa: {st.session_state.enunciado} con {rubrica_txt}. JSON format. REGLA: No 'Tú/Usted', tono cálido. Trabajo: {contenido[:15000]}"
                            if "Groq" in motor_ia:
                                client = Groq(api_key=groq_key)
                                chat = client.chat.completions.create(model=modelo_seleccionado, messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
                                res = json.loads(chat.choices[0].message.content)
                                st.session_state['tokens_acumulados'] += chat.usage.total_tokens
                            else:
                                genai.configure(api_key=gemini_key)
                                model = genai.GenerativeModel(modelo_seleccionado)
                                chat = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
                                res = json.loads(chat.text)
                                st.session_state['tokens_acumulados'] += model.count_tokens(prompt).total_tokens

                            html = st.session_state.plantilla.replace('REEMPLAZO_P1', res['p1']).replace('REEMPLAZO_P2', res['p2']).replace('REEMPLAZO_P3', res['p3'])
                            
                            with log_container:
                                st.success(f"✅ {nombre} calificado | Nota: {res['nota']}")
                                with st.expander(f"Borrador", expanded=True):
                                    components.html(html, height=150, scrolling=True)
                            
                            st.session_state['estudiantes_evaluados'].append({'nombre': nombre, 'student_id': sid, 'nota': float(res['nota']), 'html_final': html})
                        except Exception as e:
                            with log_container: st.error(f"❌ Error con {nombre}: {str(e)}")
                    
                    progreso.progress((idx + 1) / len(df_final))
                status_box.success("🎉 Ciclo terminado.")

# 6. Sincronización
if st.session_state['estudiantes_evaluados']:
    st.divider()
    if st.button("📤 SINCRONIZAR TODO CON CANVAS", type="primary", use_container_width=True):
        for idx_s, est in enumerate(st.session_state['estudiantes_evaluados']):
            st.toast(f"🚀 Subiendo nota de {est['nombre']}")
            enviar_nota_canvas(st.sidebar.text_input('Dom.', value='https://uniminuto.instructure.com'), canvas_token, curso_id, actividad_id, est['student_id'], est['nota'], est['html_final'])
        st.balloons()
        st.session_state['estudiantes_evaluados'] = []
        st.session_state['tokens_acumulados'] = 0
        time.sleep(1)
        st.rerun()
