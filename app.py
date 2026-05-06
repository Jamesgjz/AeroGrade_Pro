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

# Inicialización de memoria persistente
if 'estudiantes_evaluados' not in st.session_state:
    st.session_state['estudiantes_evaluados'] = []

# 2. Motor de Envío a Canvas
def enviar_nota_canvas(domain, token, course_id, assignment_id, student_id, nota, comentario_html):
    url = f"{domain.rstrip('/')}/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/{student_id}"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "submission[posted_grade]": nota,
        "comment[text_comment]": comentario_html
    }
    try:
        response = requests.put(url, headers=headers, data=payload)
        response.raise_for_status()
        return True
    except:
        return False

# 3. Configuración Técnica (Sidebar)
st.sidebar.header("⚙️ Configuración")
groq_api_key = st.secrets.get("GROQ_API_KEY", "")
canvas_token = st.sidebar.text_input("Canvas API Token", type="password")
canvas_domain = st.sidebar.text_input('🌐 Dominio', value='https://uniminuto.instructure.com')
curso_id = st.sidebar.text_input('🏫 ID Curso', value='11731')
actividad_id = st.sidebar.text_input('📝 ID Actividad', value='208144')

# 4. Panel del Docente
st.title("🛡️ AeroGrade Pro: Evaluación con Enfoque Humano")
st.markdown("---")

col_params1, col_params2 = st.columns(2)
with col_params1:
    st.session_state.enunciado = st.text_area("📝 Enunciado de la Actividad:", height=150, placeholder="Instrucciones que diste a los alumnos...")
with col_params2:
    st.session_state.plantilla = st.text_area("🖥️ Plantilla HTML:", height=150, placeholder="Código HTML con REEMPLAZO_P1, REEMPLAZO_P2, REEMPLAZO_P3")

# 5. Gestión de Archivos
st.subheader("📤 Insumos Académicos")
c1, c2, c3 = st.columns(3)
with c1: archivo_calificaciones = st.file_uploader("CSV de Canvas", type=["csv"])
with c2: archivo_rubricas = st.file_uploader("CSV de Rúbricas", type=["csv"])
with c3: archivo_zip = st.file_uploader('📦 ZIP de Entregas', type=['zip'])

if archivo_calificaciones and archivo_rubricas:
    df_cal = pd.read_csv(archivo_calificaciones)
    df_rub = pd.read_csv(archivo_rubricas)
    
    # Detección automática de columnas de evaluación
    columnas_act = [col for col in df_cal.columns if any(k in col for k in ['MA Evaluación', 'MT Evaluación', 'MT Evidencia'])]
    
    if columnas_act:
        actividad_sel = st.selectbox("🎯 SELECCIONE LA ACTIVIDAD:", ["-- Seleccione --"] + columnas_act)
        
        if actividad_sel != "-- Seleccione --":
            rubrica_sel = st.selectbox('Rúbrica asociada:', df_rub['Rubric Name'].unique())
            rubrica_txt = df_rub[df_rub['Rubric Name'] == rubrica_sel].to_csv(index=False)
            
            # Filtro de estudiantes (evitando filas de puntos posibles)
            df_final = df_cal[df_cal['Student'].astype(str).str.strip() != 'Points Possible'].copy()
            
            # MOSTRAR LO QUE YA SE HA EVALUADO (Mejora: Visibilidad)
            if st.session_state['estudiantes_evaluados']:
                st.markdown("---")
                st.subheader(f"✅ Borradores listos ({len(st.session_state['estudiantes_evaluados'])})")
                for e_listo in st.session_state['estudiantes_evaluados']:
                    with st.expander(f"🧑‍🎓 {e_listo['nombre']} - Nota: {e_listo['nota']}"):
                        components.html(e_listo['html_final'], height=150, scrolling=True)

            # Botones de Acción
            st.markdown("---")
            b1, b2 = st.columns(2)
            with b1:
                btn_iniciar = st.button('🚀 Iniciar / Continuar Evaluación', type="primary", use_container_width=True)
            with b2:
                if st.button("🧹 Empezar de Cero", use_container_width=True):
                    num = len(st.session_state['estudiantes_evaluados'])
                    st.session_state['estudiantes_evaluados'] = []
                    st.toast(f"Memoria limpia: Se borraron {num} borradores.", icon="🧹")
                    time.sleep(1)
                    st.rerun()

            # LÓGICA DE EVALUACIÓN
            if btn_iniciar:
                if not groq_api_key:
                    st.error("Falta la API Key de Groq en los Secrets.")
                    st.stop()
                
                client = Groq(api_key=groq_api_key)
                ids_listos = [e['student_id'] for e in st.session_state['estudiantes_evaluados']]
                
                progreso = st.progress(0)
                reloj_ia = st.empty() # Espacio para el contador de espera

                for idx, (i, row) in enumerate(df_final.iterrows()):
                    nombre = row.get('Student', 'Estudiante')
                    sid = str(int(float(row.get('ID', 0))))
                    nota_canvas = row[actividad_sel]
                    
                    # Saltar si ya está calificado o en memoria
                    if (pd.notna(nota_canvas) and str(nota_canvas).strip() not in ['', '-']) or sid in ids_listos:
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
                                    if ext.endswith(('.java', '.py', '.txt', '.sql', '.r', '.html', '.css', '.js', '.cpp', '.c')):
                                        contenido += f"\n--- ARCHIVO: {f_name} ---\n"
                                        contenido += f.read().decode('utf-8', errors='ignore')
                                    elif ext.endswith('.pdf'):
                                        reader = PyPDF2.PdfReader(io.BytesIO(f.read()))
                                        for p in reader.pages: contenido += p.extract_text()
                    
                    if contenido:
                        prompt = f"""Actúa como profesor de UNIMINUTO. Evalúa según:
                        ENUNCIADO: {st.session_state.enunciado}
                        RÚBRICA: {rubrica_txt}
                        REGLAS: Prohibido iniciar con 'Tú' o 'Usted'. Tono cálido. No usar 'crucial' ni 'clave'.
                        JSON: {{"nota": decimal, "p1": "logros", "p2": "mejoras", "p3": "referencias"}}
                        TRABAJO: {contenido[:8000]}"""

                        evaluado = False
                        while not evaluado:
                            try:
                                chat = client.chat.completions.create(
                                    model="llama-3.3-70b-versatile",
                                    messages=[{"role": "user", "content": prompt}],
                                    response_format={"type": "json_object"},
                                    temperature=0.3
                                )
                                res = json.loads(chat.choices[0].message.content)
                                html = st.session_state.plantilla.replace('REEMPLAZO_P1', res['p1']).replace('REEMPLAZO_P2', res['p2']).replace('REEMPLAZO_P3', res['p3'])
                                
                                st.session_state['estudiantes_evaluados'].append({
                                    'nombre': nombre, 'student_id': sid, 'nota': float(res['nota']), 'html_final': html
                                })
                                evaluado = True
                                st.rerun() # Actualiza la lista visual inmediatamente
                                
                            except Exception as e:
                                if "429" in str(e):
                                    for t in range(660, 0, -1):
                                        reloj_ia.error(f"🛑 Límite alcanzado. Retomando en {t//60:02d}:{t%60:02d}. No cierres la app.")
                                        time.sleep(1)
                                    reloj_ia.empty()
                                else:
                                    st.error(f"Error con {nombre}: {e}")
                                    evaluado = True

                    progreso.progress((idx + 1) / len(df_final))

# 6. Sincronización Masiva
if st.session_state['estudiantes_evaluados']:
    st.divider()
    if st.button("📤 SUBIR TODO A CANVAS", type="primary", use_container_width=True):
        total = len(st.session_state['estudiantes_evaluados'])
        for idx_c, est in enumerate(st.session_state['estudiantes_evaluados']):
            # Mejora: Notificación tipo Pop-up (Toast)
            st.toast(f"🚀 Sincronizando ({idx_c + 1}/{total}): {est['nombre']}", icon="⏳")
            enviar_nota_canvas(canvas_domain, canvas_token, curso_id, actividad_id, est['student_id'], est['nota'], est['html_final'])
        
        st.balloons()
        st.success(f"¡Sincronización completa! {total} estudiantes actualizados.")
        st.session_state['estudiantes_evaluados'] = []
        time.sleep(2)
        st.rerun()
