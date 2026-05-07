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

# 2. Función de Envío a Canvas
def enviar_nota_canvas(domain, token, course_id, assignment_id, student_id, nota, comentario_html):
    url = f"{domain.rstrip('/')}/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/{student_id}"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"submission[posted_grade]": nota, "comment[text_comment]": comentario_html}
    try:
        response = requests.put(url, headers=headers, data=payload)
        return response.status_code == 200
    except: return False

# 3. Sidebar
st.sidebar.header("⚙️ Configuración")
motor_ia = st.sidebar.selectbox("Seleccione Motor:", ["Groq (Gratis)", "Gemini (Pago)"])
groq_key = st.secrets.get("GROQ_API_KEY", "")
gemini_key = st.sidebar.text_input("Gemini Key:", type="password") if "Gemini" in motor_ia else ""
canvas_token = st.sidebar.text_input("Canvas Token", type="password")
canvas_domain = st.sidebar.text_input('Dominio', value='https://uniminuto.instructure.com')
curso_id = st.sidebar.text_input('ID Curso', value='11731')
actividad_id = st.sidebar.text_input('ID Actividad', value='208144')

st.title("🛡️ AeroGrade Pro: Evaluación en Tiempo Real")
st.markdown("---")

# 4. Parámetros
c_p1, c_p2 = st.columns(2)
with c_p1: st.session_state.enunciado = st.text_area("📝 Enunciado:", height=100)
with c_p2: st.session_state.plantilla = st.text_area("🖥️ Plantilla HTML:", height=100)

# 5. Carga de Insumos
st.subheader("📤 Archivos")
c1, c2, c3 = st.columns(3)
with c1: archivo_calificaciones = st.file_uploader("CSV Calificaciones", type=["csv"])
with c2: archivo_rubricas = st.file_uploader("CSV Rúbricas", type=["csv"])
with c3: archivo_zip = st.file_uploader('ZIP Entregas', type=['zip'])

if archivo_calificaciones and archivo_rubricas:
    df_cal = pd.read_csv(archivo_calificaciones)
    df_rub = pd.read_csv(archivo_rubricas)
    columnas_act = [col for col in df_cal.columns if any(k in col for k in ['MA Evaluación', 'MT Evaluación', 'MT Evidencia'])]
    
    if columnas_act:
        actividad_sel = st.selectbox("🎯 ACTIVIDAD:", ["-- Seleccione --"] + columnas_act)
        
        if actividad_sel != "-- Seleccione --":
            rubrica_sel = st.selectbox('Rúbrica:', df_rub['Rubric Name'].unique())
            rubrica_txt = df_rub[df_rub['Rubric Name'] == rubrica_sel].to_csv(index=False)
            df_final = df_cal[df_cal['Student'].astype(str).str.strip() != 'Points Possible'].copy()
            df_final = df_final[df_final['ID'].notna()]

            # --- MONITOR DE CONSUMO ---
            m1, m2 = st.columns(2)
            m1.metric("Tokens", f"{st.session_state['tokens_acumulados']:,}")
            m2.metric("Motor Activo", motor_ia.split(" ")[0])

            # --- LISTA DE CLASE ---
            with st.expander("Ver lista de estudiantes", expanded=False):
                st.dataframe(df_final[['Student', 'ID', 'Section']], use_container_width=True)

            # --- VISUALIZACIÓN DE LO YA CALIFICADO ---
            if st.session_state['estudiantes_evaluados']:
                st.subheader("✅ Borradores Listos")
                for e in st.session_state['estudiantes_evaluados']:
                    with st.expander(f"🧑‍🎓 {e['nombre']} - Nota: {e['nota']}", expanded=False):
                        components.html(e['html_final'], height=150, scrolling=True)

            st.divider()
            if st.button('🚀 INICIAR CALIFICACIÓN VISUAL', type="primary", use_container_width=True):
                progreso = st.progress(0)
                status_text = st.empty() # Para mostrar a quién califica
                log_container = st.container() # Para mostrar la nota y comentario en vivo

                for idx, (i, row) in enumerate(df_final.iterrows()):
                    nombre = row.get('Student', 'Estudiante')
                    sid = str(int(float(row.get('ID', 0))))
                    
                    if sid in [e['student_id'] for e in st.session_state['estudiantes_evaluados']]:
                        progreso.progress((idx + 1) / len(df_final))
                        continue
                    
                    status_text.info(f"🔍 Procesando a: **{nombre}** (ID: {sid})")
                    
                    contenido = ""
                    if archivo_zip:
                        with zipfile.ZipFile(archivo_zip, 'r') as z:
                            archivos_alumno = [f for f in z.namelist() if sid in f]
                            if not archivos_alumno:
                                log_container.warning(f"⚠️ No se encontró archivo ZIP para {nombre}")
                            for f_name in archivos_alumno:
                                with z.open(f_name) as f:
                                    ext = f_name.lower()
                                    if ext.endswith(('.java', '.py', '.txt', '.sql', '.r', '.html', '.css', '.js', '.xml')):
                                        contenido += f.read().decode('utf-8', errors='ignore')
                                    elif ext.endswith('.pdf'):
                                        reader = PyPDF2.PdfReader(io.BytesIO(f.read()))
                                        for p in reader.pages: contenido += p.extract_text()
                    
                    if contenido:
                        prompt = f"Profesor Uniminuto. Evalúa: {st.session_state.enunciado} con {rubrica_txt}. JSON format. Trabajo: {contenido[:8000]}"
                        try:
                            if "Groq" in motor_ia:
                                client = Groq(api_key=groq_key)
                                chat = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
                                res = json.loads(chat.choices[0].message.content)
                                st.session_state['tokens_acumulados'] += chat.usage.total_tokens
                            else:
                                genai.configure(api_key=gemini_key)
                                model = genai.GenerativeModel('gemini-1.5-flash')
                                chat = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
                                res = json.loads(chat.text)
                                st.session_state['tokens_acumulados'] += model.count_tokens(prompt).total_tokens

                            html = st.session_state.plantilla.replace('REEMPLAZO_P1', res['p1']).replace('REEMPLAZO_P2', res['p2']).replace('REEMPLAZO_P3', res['p3'])
                            
                            # MOSTRAR EN VIVO (Igual que el original)
                            with log_container:
                                st.success(f"✅ Calificado: {nombre} - Nota: {res['nota']}")
                                with st.expander("Ver comentario generado", expanded=True):
                                    components.html(html, height=150, scrolling=True)
                            
                            st.session_state['estudiantes_evaluados'].append({'nombre': nombre, 'student_id': sid, 'nota': float(res['nota']), 'html_final': html})
                            
                        except Exception as e:
                            if "429" in str(e):
                                status_text.error(f"🛑 Límite de IA alcanzado. Esperando...")
                                time.sleep(60)
                            else: log_container.error(f"❌ Error con {nombre}: {e}")
                    
                    progreso.progress((idx + 1) / len(df_final))
                
                status_text.success("🎉 ¡Proceso finalizado! Revisa los borradores arriba y sube a Canvas.")

# 6. Sincronización
if st.session_state['estudiantes_evaluados']:
    st.divider()
    if st.button("📤 SUBIR TODO A CANVAS", type="primary", use_container_width=True):
        for idx_c, est in enumerate(st.session_state['estudiantes_evaluados']):
            st.toast(f"🚀 Sincronizando: {est['nombre']}")
            enviar_nota_canvas(canvas_domain, canvas_token, curso_id, actividad_id, est['student_id'], est['nota'], est['html_final'])
        st.balloons()
        st.session_state['estudiantes_evaluados'] = []
        st.session_state['tokens_acumulados'] = 0
        time.sleep(2)
        st.rerun()
