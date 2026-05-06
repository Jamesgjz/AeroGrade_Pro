import streamlit as st
import pandas as pd
import requests
import re
import json
import io
import zipfile
import PyPDF2
import docx
import openpyxl
from bs4 import BeautifulSoup
import streamlit.components.v1 as components
from groq import Groq

# 1. Configuración Inicial de la Aplicación
st.set_page_config(page_title="AeroGrade Pro - UNIMINUTO", layout="wide")

if 'estudiantes_evaluados' not in st.session_state:
    st.session_state['estudiantes_evaluados'] = []

# 2. Función de Envío a Canvas
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
    except Exception as e:
        return False

# 3. Barra Lateral (Parámetros Técnicos)
st.sidebar.header("⚙️ Configuración Canvas y API")
canvas_token = st.sidebar.text_input("Canvas API Token", type="password")
canvas_domain = st.sidebar.text_input('🌐 Dominio de Canvas', value='https://uniminuto.instructure.com')
curso_id = st.sidebar.text_input('🏫 ID del Curso en Canvas', value='11731')
actividad_id = st.sidebar.text_input('📝 ID de la Actividad', value='208144')

# 4. Interfaz - Configuración del Docente
st.title("🛡️ AeroGrade Pro: Evaluación con Enfoque Humano")
st.markdown("---")

col1, col2 = st.columns(2)
with col1:
    st.session_state.enunciado = st.text_area(
        "📝 Pega aquí el Enunciado de Canvas:", 
        value=st.session_state.get('enunciado', ''), 
        height=200
    )
with col2:
    st.session_state.plantilla = st.text_area(
        "🖥️ Pega aquí el código HTML de la plantilla (REEMPLAZO_P1...):", 
        value=st.session_state.get('plantilla', ''), 
        height=200
    )

# 5. Carga de Insumos Académicos
st.subheader("📤 Archivos de Calificación")
col_csv1, col_csv2, col_zip = st.columns(3)
with col_csv1:
    archivo_calificaciones = st.file_uploader("Sube el CSV de calificaciones", type=["csv"])
with col_csv2:
    archivo_rubricas = st.file_uploader("Sube el CSV de rúbricas", type=["csv"])
with c_zip := col_zip:
    archivo_zip = st.file_uploader('📦 Sube el .zip de entregas (Máx 1GB)', type=['zip'])

if archivo_calificaciones and archivo_rubricas:
    df_calificaciones = pd.read_csv(archivo_calificaciones)
    df_rubricas = pd.read_csv(archivo_rubricas)
    
    columnas_actividad = [col for col in df_calificaciones.columns if any(k in col for k in ['MA Evaluación', 'MT Evaluación', 'MT Evidencia'])]
    
    if columnas_actividad:
        st.markdown("---")
        st.error("⚠️ ¡ATENCIÓN DOCENTE! Recuerde SELECCIONAR LA ACTIVIDAD en el menú desplegable de abajo antes de iniciar.")
        actividad_seleccionada = st.selectbox("🎯 SELECCIONE LA ACTIVIDAD A CALIFICAR:", ["-- Seleccione una actividad --"] + columnas_actividad)
        
        if actividad_seleccionada != "-- Seleccione una actividad --":
            rubrica_seleccionada = st.selectbox('Selecciona la rúbrica correspondiente:', df_rubricas['Rubric Name'].unique())
            rubrica_texto = df_rubricas[df_rubricas['Rubric Name'] == rubrica_seleccionada].to_csv(index=False)
            
            df_filtrado = df_calificaciones[df_calificaciones['Student'].astype(str).str.strip() != 'Points Possible'].copy()
            
            if 'MA' in actividad_seleccionada:
                df_filtrado = df_filtrado[df_filtrado['Section'].astype(str).str.contains('Actividades', na=False)]
            elif 'MT' in actividad_seleccionada:
                df_filtrado = df_filtrado[df_filtrado['Section'].astype(str).str.contains('Trabajo Final', na=False)]
                
            total_estudiantes = len(df_filtrado)
            
            if total_estudiantes > 0:
                st.write(f"📋 **Estudiantes detectados para evaluación: {total_estudiantes}**")
                st.dataframe(df_filtrado[['Student', 'ID', 'Section', actividad_seleccionada]])
                
                if st.button('🚀 Iniciar Calificación en Tiempo Real'):
                    if not canvas_token or "GROQ_API_KEY" not in st.secrets:
                        st.error("Faltan credenciales (Canvas Token o Groq API Key).")
                        st.stop()
                    
                    client = Groq(api_key=st.secrets["GROQ_API_KEY"])
                    st.session_state['estudiantes_evaluados'] = []
                    
                    barra_progreso = st.progress(0)
                    st.markdown("### ✍️ Generando borradores...")
                    contenedor_en_vivo = st.container()
                    
                    for idx, (i, row) in enumerate(df_filtrado.iterrows()):
                        nombre_estudiante = row.get('Student', 'Desconocido')
                        student_id = str(int(float(row.get('ID', 0))))
                        nota_actual = row[actividad_seleccionada]
                        
                        if pd.notna(nota_actual) and str(nota_actual).strip() not in ['', '-']:
                            with contenedor_en_vivo:
                                st.info(f'⏭️ {nombre_estudiante} ya tiene nota. Omitiendo...')
                            barra_progreso.progress((idx + 1) / total_estudiantes)
                            continue
                            
                        texto_extraido = ""
                        if archivo_zip:
                            with zipfile.ZipFile(archivo_zip, 'r') as z:
                                matching_files = [f for f in z.namelist() if student_id in f]
                                for f_name in matching_files:
                                    with z.open(f_name) as f:
                                        if f_name.endswith(('.java', '.txt', '.sql', '.html', '.py', '.r', '.csv')):
                                            texto_extraido += f.read().decode('utf-8', errors='ignore') + "\n"
                                        elif f_name.endswith('.pdf'):
                                            reader = PyPDF2.PdfReader(io.BytesIO(f.read()))
                                            for p in reader.pages: texto_extraido += p.extract_text() + "\n"
                                        elif f_name.endswith('.docx'):
                                            doc = docx.Document(io.BytesIO(f.read()))
                                            texto_extraido += "\n".join([para.text for para in doc.paragraphs]) + "\n"
                        
                        if texto_extraido:
                            prompt = f"""Actúa como un profesor experto de UNIMINUTO. 
Evalúa este trabajo basándote en el ENUNCIADO y la RÚBRICA proporcionados.

ENUNCIADO: {st.session_state.enunciado}
RÚBRICA: {rubrica_texto}

ESTILO DE COMUNICACIÓN OBLIGATORIO:
- Escribe siempre en segunda persona ("tú").
- El tono debe ser sumamente cercano, cómodo, cálido y muy personal. Queremos que el estudiante sienta que lo está leyendo un mentor humano que valora genuinamente su esfuerzo.
- Evita por completo sonar como un robot, usar frases de cajón o expresiones genéricas. Háblale como si estuvieran sentados conversando amigablemente sobre su proceso de aprendizaje.

REGLAS TÉCNICAS:
- NOTA: Número decimal de 0.0 a 5.0. NUNCA uses escala de 10 o 100.
- PROHIBICIÓN DE VOCABULARIO: BAJO NINGUNA CIRCUNSTANCIA uses las palabras "crucial" ni "clave". Cámbialas por "fundamental", "esencial" o "importante".
- ESTRUCTURA:
  - p1 (Logros): Un párrafo destacando lo que hizo bien.
  - p2 (Mejoras): Un párrafo constructivo. NO sugieras reenvíos.
  - p3 (Material): Un párrafo con una referencia bibliográfica en español y una en inglés.

ENTREGA:
{texto_extraido[:8500]}

RESPONDE SOLO CON JSON: {{"nota": decimal, "p1": "texto", "p2": "texto", "p3": "texto"}}"""

                            try:
                                resp = client.chat.completions.create(
                                    model="llama-3.3-70b-versatile",
                                    messages=[{"role": "user", "content": prompt}],
                                    response_format={"type": "json_object"},
                                    temperature=0.3
                                )
                                
                                res = json.loads(resp.choices[0].message.content)
                                html_f = st.session_state.plantilla.replace('REEMPLAZO_P1', res['p1']).replace('REEMPLAZO_P2', res['p2']).replace('REEMPLAZO_P3', res['p3'])
                                
                                st.session_state['estudiantes_evaluados'].append({
                                    'nombre': nombre_estudiante,
                                    'student_id': student_id,
                                    'nota': float(res['nota']),
                                    'html_final': html_f
                                })
                                
                                with contenedor_en_vivo:
                                    if float(res['nota']) < 3.5:
                                        st.warning(f"⚠️ REVISIÓN REQUERIDA: {nombre_estudiante} tiene nota inferior a 3.5 ({res['nota']})")
                                    with st.expander(f"🧑‍🎓 {nombre_estudiante} - Nota: {res['nota']}", expanded=True):
                                        components.html(html_f, height=200, scrolling=True)
                                    
                            except Exception as e:
                                with contenedor_en_vivo: st.error(f"Error con {nombre_estudiante}: {e}")
                        
                        barra_progreso.progress((idx + 1) / total_estudiantes)
                    
                    st.success("✅ Evaluación terminada. Revisa los comentarios arriba y sincroniza al final de la página.")

# 6. Sincronización Final
if st.session_state.get('estudiantes_evaluados'):
    st.divider()
    st.subheader("🚀 Sincronización Masiva con Canvas")
    if st.button("📤 SUBIR TODAS LAS NOTAS AHORA", type="primary"):
        b_envio = st.progress(0)
        total_e = len(st.session_state['estudiantes_evaluados'])
        for idx_e, est in enumerate(st.session_state['estudiantes_evaluados']):
            enviar_nota_canvas(canvas_domain, canvas_token, curso_id, actividad_id, est['student_id'], est['nota'], est['html_final'])
            b_envio.progress((idx_e + 1) / total_e)
        st.balloons()
        st.success("¡Proceso completado exitosamente!")
        st.session_state['estudiantes_evaluados'] = []
