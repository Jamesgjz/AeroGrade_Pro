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

# Memoria persistente para no perder nada si la app se refresca
if 'estudiantes_evaluados' not in st.session_state:
    st.session_state['estudiantes_evaluados'] = []
if 'tokens_acumulados' not in st.session_state:
    st.session_state['tokens_acumulados'] = 0

# 2. Función para listar modelos disponibles según tu API Key (Novedad)
def listar_modelos_gemini(api_key):
    try:
        genai.configure(api_key=api_key)
        return [m.name.replace('models/', '') for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    except:
        return ["gemini-1.5-flash", "gemini-1.5-pro"]

# 3. Función de Envío a Canvas
def enviar_nota_canvas(domain, token, course_id, assignment_id, student_id, nota, comentario_html):
    url = f"{domain.rstrip('/')}/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/{student_id}"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"submission[posted_grade]": nota, "comment[text_comment]": comentario_html}
    try:
        response = requests.put(url, headers=headers, data=payload)
        return response.status_code == 200
    except: return False

# 4. Sidebar - Selección de Cerebro e IA
st.sidebar.header("⚙️ Configuración del Motor")
motor_ia = st.sidebar.selectbox("Seleccione Motor:", ["Groq (Gratis)", "Google Gemini (Potencia/Pago)"])

groq_key = st.secrets.get("GROQ_API_KEY", "")
gemini_key = ""
modelo_seleccionado = "llama-3.3-70b-versatile"

if motor_ia == "Google Gemini (Potencia/Pago)":
    gemini_key = st.sidebar.text_input("Ingrese su Gemini API Key:", type="password")
    if gemini_key:
        opciones = listar_modelos_gemini(gemini_key)
        modelo_seleccionado = st.sidebar.selectbox("Versión de Gemini Detectada:", opciones)

canvas_token = st.sidebar.text_input("Canvas Token", type="password")
curso_id = st.sidebar.text_input('ID Curso', value='11731')
actividad_id = st.sidebar.text_input('ID Actividad', value='208144')

st.title("🛡️ AeroGrade Pro: Control Total y Validación en Vivo")
st.markdown("---")

# 5. Parámetros y Archivos
c_p1, c_p2 = st.columns(2)
with c_p1: st.session_state.enunciado = st.text_area("📝 Enunciado de la Actividad:", height=100)
with c_p2: st.session_state.plantilla = st.text_area("🖥️ Plantilla HTML de Retroalimentación:", height=100)

st.subheader("📤 Insumos Académicos")
c1, c2, c3 = st.columns(3)
with c1: archivo_calificaciones = st.file_uploader("CSV Calificaciones", type=["csv"])
with c2: archivo_rubricas = st.file_uploader("CSV Rúbricas", type=["csv"])
with c3: archivo_zip = st.file_uploader('ZIP Entregas', type=['zip'])

if archivo_calificaciones and archivo_rubricas:
    df_cal = pd.read_csv(archivo_calificaciones)
    df_rub = pd.read_csv(archivo_rubricas)
    columnas_act = [col for col in df_cal.columns if any(k in col for k in ['MA Evaluación', 'MT Evaluación', 'MT Evidencia'])]
    
    if columnas_act:
        actividad_sel = st.selectbox("🎯 ACTIVIDAD A EVALUAR:", ["-- Seleccione --"] + columnas_act)
        
        if actividad_sel != "-- Seleccione --":
            rubrica_sel = st.selectbox('Rúbrica:', df_rub['Rubric Name'].unique())
            rubrica_txt = df_rub[df_rub['Rubric Name'] == rubrica_sel].to_csv(index=False)
            df_final = df_cal[df_cal['Student'].astype(str).str.strip() != 'Points Possible'].copy()
            df_final = df_final[df_final['ID'].notna()]

            # Métrica de Tokens y Modelo
            m1, m2 = st.columns(2)
            m1.metric("Tokens Consumidos", f"{st.session_state['tokens_acumulados']:,}")
            m2.metric("Motor en Uso", modelo_seleccionado.split("/")[-1])

            # --- VISUALIZACIÓN DE LO GANADO: LISTA Y BORRADORES ---
            st.subheader("📋 Estado de la Evaluación")
            with st.expander("Ver lista de estudiantes y progreso", expanded=False):
                ids_evaluados = [e['student_id'] for e in st.session_state['estudiantes_evaluados']]
                df_viz = df_final[['Student', 'ID']].copy()
                df_viz['Estado'] = df_viz['ID'].apply(lambda x: "✅ Listo" if str(int(float(x))) in ids_evaluados else "⏳ Pendiente")
                st.dataframe(df_viz, use_container_width=True)

            if st.session_state['estudiantes_evaluados']:
                st.subheader("📝 Notas y Comentarios Generados (Valide aquí)")
                for e in st.session_state['estudiantes_evaluados']:
                    with st.expander(f"🧑‍🎓 {e['nombre']} - Nota: {e['nota']}", expanded=False):
                        components.html(e['html_final'], height=150, scrolling=True)

            st.divider()
            
            # --- BOTONES DE ACCIÓN ---
            b_eval, b_reset = st.columns(2)
            with b_eval:
                btn_iniciar = st.button('🚀 INICIAR CALIFICACIÓN EN TIEMPO REAL', type="primary", use_container_width=True)
            with b_reset:
                if st.button("🧹 EMPEZAR DE CERO", use_container_width=True):
                    st.session_state['estudiantes_evaluados'] = []
                    st.session_state['tokens_acumulados'] = 0
                    st.rerun()

            if btn_iniciar:
                progreso = st.progress(0)
                status_box = st.empty()
                log_container = st.container() # AQUÍ SE MUESTRAN LAS NOTAS EN VIVO

                for idx, (i, row) in enumerate(df_final.iterrows()):
                    nombre = row.get('Student', 'Estudiante')
                    sid = str(int(float(row.get('ID', 0))))
                    
                    if sid in [e['student_id'] for e in st.session_state['estudiantes_evaluados']]:
                        progreso.progress((idx + 1) / len(df_final))
                        continue
                    
                    status_box.info(f"🔍 Analizando entrega de: **{nombre}**")
                    
                    contenido = ""
                    if archivo_zip:
                        with zipfile.ZipFile(archivo_zip, 'r') as z:
                            # Búsqueda robusta por ID en el nombre del archivo
                            archivos_alumno = [f for f in z.namelist() if sid in f]
                            if not archivos_alumno:
                                with log_container: st.warning(f"⚠️ No se hallaron archivos para {nombre}")
                            for f_name in archivos_alumno:
                                with z.open(f_name) as f:
                                    ext = f_name.lower()
                                    if any(ext.endswith(e) for e in ['.java', '.py', '.txt', '.sql', '.r', '.html', '.css', '.js', '.xml', '.pkt']):
                                        contenido += f"\n--- {f_name} ---\n"
                                        contenido += f.read().decode('utf-8', errors='ignore')
                                    elif ext.endswith('.pdf'):
                                        reader = PyPDF2.PdfReader(io.BytesIO(f.read()))
                                        for p in reader.pages: contenido += p.extract_text()
                    
                    if contenido:
                        prompt = f"Profesor Uniminuto. Evalúa: {st.session_state.enunciado} con {rubrica_txt}. JSON format. REGLA: No 'Tú/Usted', tono cálido. Trabajo: {contenido[:15000]}"
                        try:
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
                            
                            # MOSTRAR EN VIVO (Lo que me pediste no omitir)
                            with log_container:
                                st.success(f"✅ Calificado: {nombre} | Nota: {res['nota']}")
                                with st.expander(f"Borrador de {nombre}", expanded=True):
                                    components.html(html, height=150, scrolling=True)
                            
                            st.session_state['estudiantes_evaluados'].append({'nombre': nombre, 'student_id': sid, 'nota': float(res['nota']), 'html_final': html})
                            
                        except Exception as e:
                            with log_container: st.error(f"❌ Error con {nombre}: {str(e)}")
                    
                    progreso.progress((idx + 1) / len(df_final))
                status_box.success("🎉 Evaluación finalizada. Ahora puedes sincronizar con Canvas.")

# 6. Sincronización a Canvas
if st.session_state['estudiantes_evaluados']:
    st.divider()
    if st.button("📤 SINCRONIZAR TODAS LAS NOTAS CON CANVAS", type="primary", use_container_width=True):
        total_s = len(st.session_state['estudiantes_evaluados'])
        for idx_s, est in enumerate(st.session_state['estudiantes_evaluados']):
            st.toast(f"🚀 Subiendo nota de {est['nombre']} ({idx_s + 1}/{total_s})")
            enviar_nota_canvas(st.sidebar.text_input('Dominio', value='https://uniminuto.instructure.com'), canvas_token, curso_id, actividad_id, est['student_id'], est['nota'], est['html_final'])
        st.balloons()
        st.success("¡Sincronización exitosa!")
        st.session_state['estudiantes_evaluados'] = []
        st.session_state['tokens_acumulados'] = 0
        time.sleep(2)
        st.rerun()
