import streamlit as st
import pandas as pd
import requests
import json
import io
import zipfile
import PyPDF2
import streamlit.components.v1 as components
from groq import Groq
import time

# 1. Configuración de Página
st.set_page_config(page_title="AeroGrade Pro - UNIMINUTO", layout="wide")

# Inicialización de memoria y contadores
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
    except:
        return False

# 3. Sidebar
st.sidebar.header("⚙️ Configuración Segura (Groq)")
groq_key = st.secrets.get("GROQ_API_KEY", "")
canvas_token = st.sidebar.text_input("Canvas API Token", type="password")
canvas_domain = st.sidebar.text_input('🌐 Dominio', value='https://uniminuto.instructure.com')
curso_id = st.sidebar.text_input('🏫 ID Curso', value='11731')
actividad_id = st.sidebar.text_input('📝 ID Actividad', value='208144')

st.title("🛡️ AeroGrade Pro: Monitor de Consumo Real")
st.markdown("---")

# 4. Panel de Parámetros
col_params1, col_params2 = st.columns(2)
with col_params1:
    st.session_state.enunciado = st.text_area("📝 Enunciado de la Actividad:", height=150)
with col_params2:
    st.session_state.plantilla = st.text_area("🖥️ Plantilla HTML:", height=150)

# 5. Gestión de Archivos
st.subheader("📤 Insumos Académicos")
c1, c2, c3 = st.columns(3)
with c1: archivo_calificaciones = st.file_uploader("CSV de Canvas", type=["csv"])
with c2: archivo_rubricas = st.file_uploader("CSV de Rúbricas", type=["csv"])
with c3: archivo_zip = st.file_uploader('📦 ZIP de Entregas', type=['zip'])

if archivo_calificaciones and archivo_rubricas:
    df_cal = pd.read_csv(archivo_calificaciones)
    df_rub = pd.read_csv(archivo_rubricas)
    columnas_act = [col for col in df_cal.columns if any(k in col for k in ['MA Evaluación', 'MT Evaluación', 'MT Evidencia'])]
    
    if columnas_act:
        actividad_sel = st.selectbox("🎯 SELECCIONE LA ACTIVIDAD:", ["-- Seleccione --"] + columnas_act)
        
        if actividad_sel != "-- Seleccione --":
            rubrica_sel = st.selectbox('Rúbrica asociada:', df_rub['Rubric Name'].unique())
            rubrica_txt = df_rub[df_rub['Rubric Name'] == rubrica_sel].to_csv(index=False)
            df_final = df_cal[df_cal['Student'].astype(str).str.strip() != 'Points Possible'].copy()
            df_final = df_final[df_final['ID'].notna()]

            # --- MONITOR DE USO ---
            st.markdown("### 📊 Monitor de Uso")
            m1, m2 = st.columns(2)
            m1.metric("Tokens Consumidos", f"{st.session_state['tokens_acumulados']:,}")
            m2.metric("Costo Real", "$0.00 (Plan Groq Gratis)")

            # --- LISTA DE CLASE ---
            with st.expander("Ver lista de estudiantes y estado", expanded=True):
                vista_previa = df_final[['Student', 'ID', 'Section']].copy()
                ids_evaluados = [e['student_id'] for e in st.session_state['estudiantes_evaluados']]
                vista_previa['Estado'] = vista_previa['ID'].apply(lambda x: "✅ Evaluado" if str(int(float(x))) in ids_evaluados else "⏳ Pendiente")
                st.dataframe(vista_previa, use_container_width=True)

            # --- VISUALIZACIÓN DE CALIFICACIONES ---
            if st.session_state['estudiantes_evaluados']:
                st.subheader(f"📝 Notas Generadas ({len(st.session_state['estudiantes_evaluados'])})")
                for e_listo in st.session_state['estudiantes_evaluados']:
                    with st.expander(f"🧑‍🎓 {e_listo['nombre']} - Nota: {e_listo['nota']}"):
                        components.html(e_listo['html_final'], height=150, scrolling=True)

            st.divider()
            b1, b2 = st.columns(2)
            with b1:
                btn_iniciar = st.button('🚀 Iniciar Evaluación con Groq', type="primary", use_container_width=True)
            with b2:
                if st.button("🧹 Empezar de Cero", use_container_width=True):
                    st.session_state['estudiantes_evaluados'] = []
                    st.session_state['tokens_acumulados'] = 0
                    st.rerun()

            if btn_iniciar:
                if not groq_key:
                    st.error("⚠️ No hay API Key de Groq en los Secrets.")
                    st.stop()
                
                client = Groq(api_key=groq_key)
                progreso = st.progress(0)
                reloj_ia = st.empty()

                for idx, (i, row) in enumerate(df_final.iterrows()):
                    nombre = row.get('Student', 'Estudiante')
                    sid = str(int(float(row.get('ID', 0))))
                    
                    if sid in [e['student_id'] for e in st.session_state['estudiantes_evaluados']]:
                        progreso.progress((idx + 1) / len(df_final))
                        continue
                    
                    # Extracción de contenido
                    contenido = ""
                    if archivo_zip:
                        with zipfile.ZipFile(archivo_zip, 'r') as z:
                            archivos_alumno = [f for f in z.namelist() if sid in f]
                            for f_name in archivos_alumno:
                                with z.open(f_name) as f:
                                    ext = f_name.lower()
                                    if ext.endswith(('.java', '.py', '.txt', '.sql', '.r', '.html', '.css', '.js')):
                                        contenido += f.read().decode('utf-8', errors='ignore')
                                    elif ext.endswith('.pdf'):
                                        reader = PyPDF2.PdfReader(io.BytesIO(f.read()))
                                        for p in reader.pages: contenido += p.extract_text()
                    
                    if contenido:
                        prompt = f"Profesor Uniminuto. Evalúa: {st.session_state.enunciado} con {rubrica_txt}. JSON format. Trabajo: {contenido[:8000]}"
                        try:
                            chat = client.chat.completions.create(
                                model="llama-3.3-70b-versatile",
                                messages=[{"role": "user", "content": prompt}],
                                response_format={"type": "json_object"}
                            )
                            res = json.loads(chat.choices[0].message.content)
                            st.session_state['tokens_acumulados'] += chat.usage.total_tokens
                            
                            html = st.session_state.plantilla.replace('REEMPLAZO_P1', res['p1']).replace('REEMPLAZO_P2', res['p2']).replace('REEMPLAZO_P3', res['p3'])
                            st.session_state['estudiantes_evaluados'].append({
                                'nombre': nombre, 'student_id': sid, 'nota': float(res['nota']), 'html_final': html
                            })
                            # Esto fuerza a la app a mostrar el avance inmediatamente
                            st.rerun() 
                            
                        except Exception as e:
                            if "429" in str(e):
                                for t in range(660, 0, -1):
                                    reloj_ia.error(f"🛑 Límite de Groq. Retomando en {t//60:02d}:{t%60:02d}")
                                    time.sleep(1)
                                reloj_ia.empty()
                    progreso.progress((idx + 1) / len(df_final))

# 6. Sincronización
if st.session_state['estudiantes_evaluados']:
    st.divider()
    if st.button("📤 SUBIR TODO A CANVAS AHORA", type="primary", use_container_width=True):
        for idx_c, est in enumerate(st.session_state['estudiantes_evaluados']):
            st.toast(f"🚀 Sincronizando: {idx_c + 1} de {len(st.session_state['estudiantes_evaluados'])}")
            enviar_nota_canvas(canvas_domain, canvas_token, curso_id, actividad_id, est['student_id'], est['nota'], est['html_final'])
        st.balloons()
        st.session_state['estudiantes_evaluados'] = []
        st.session_state['tokens_acumulados'] = 0
        time.sleep(1)
        st.rerun()
