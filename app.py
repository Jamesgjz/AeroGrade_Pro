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

# 1. Configuración Inicial
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

# 3. Barra Lateral
st.sidebar.header("⚙️ Configuración Canvas y API")
canvas_token = st.sidebar.text_input("Canvas API Token", type="password")
canvas_domain = st.sidebar.text_input('🌐 Dominio de Canvas', value='https://uniminuto.instructure.com')
curso_id = st.sidebar.text_input('🏫 ID del Curso en Canvas', value='11731')
actividad_id = st.sidebar.text_input('📝 ID de la Actividad', value='208144')

# 4. Interfaz - Campos Limpios
st.title("🛡️ AeroGrade Pro: Evaluación y Sincronización")
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

# 5. Carga de Archivos
st.subheader("📤 Archivos de Calificación")
col_csv1, col_csv2, col_zip = st.columns(3)
with col_csv1:
    archivo_calificaciones = st.file_uploader("Sube el CSV de calificaciones", type=["csv"])
with col_csv2:
    archivo_rubricas = st.file_uploader("Sube el CSV de rúbricas", type=["csv"])
with col_zip:
    archivo_zip = st.file_uploader('📦 Sube el .zip de entregas (Máx 1GB)', type=['zip'])

if archivo_calificaciones and archivo_rubricas:
    df_calificaciones = pd.read_csv(archivo_calificaciones)
    df_rubricas = pd.read_csv(archivo_rubricas)
    
    columnas_actividad = [col for col in df_calificaciones.columns if any(k in col for k in ['MA Evaluación', 'MT Evaluación', 'MT Evidencia'])]
    
    if columnas_actividad:
        st.markdown("---")
        # 🚨 ALERTA VISUAL justificada sobre el selector
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
            
            if total_estudiantes == 0:
                st.warning("No se encontraron estudiantes para la actividad o sección seleccionada. Revisa el archivo CSV.")
            else:
                columnas_mostrar = ['Student', 'ID', 'Section', actividad_seleccionada]
                columnas_mostrar_existentes = [col for col in columnas_mostrar if col in df_filtrado.columns]
                
                st.write("📋 **Estudiantes detectados para esta actividad:**")
                st.dataframe(df_filtrado[columnas_mostrar_existentes])
                
                # BOTÓN DE PROCESAMIENTO
                if st.button('🚀 Iniciar Generación de Borradores (Vista Previa)'):
                    if not canvas_token or not curso_id:
                        st.error("⚠️ Faltan datos de Canvas en la barra lateral.")
                        st.stop()
                    if "GROQ_API_KEY" not in st.secrets:
                        st.error("⚠️ Falta configurar GROQ_API_KEY en los Secrets de Streamlit.")
                        st.stop()
                        
                    client = Groq(api_key=st.secrets["GROQ_API_KEY"])
                    st.session_state['estudiantes_evaluados'] = []
                    
                    barra_progreso = st.progress(0)
                    
                    for idx, (i, row) in enumerate(df_filtrado.iterrows()):
                        nombre_estudiante = row.get('Student', 'Desconocido')
                        student_id = str(int(float(row.get('ID', 0))))
                        nota_actual = row[actividad_seleccionada]
                        
                        if pd.notna(nota_actual) and str(nota_actual).strip() not in ['', '-']:
                            st.info(f'⏭️ {nombre_estudiante} ya tiene nota. Omitiendo...')
                            barra_progreso.progress((idx + 1) / total_estudiantes)
                            continue
                            
                        texto_extraido = ""
                        if archivo_zip:
                            with zipfile.ZipFile(archivo_zip, 'r') as z:
                                archivos_estudiante = [f for f in z.namelist() if student_id in f]
                                for f_name in archivos_estudiante:
                                    with z.open(f_name) as f:
                                        # Soporte ampliado para lectura de archivos dentro del ZIP
                                        if f_name.endswith(('.java', '.txt', '.sql', '.html', '.py', '.r', '.csv')):
                                            texto_extraido += f.read().decode('utf-8', errors='ignore') + "\n"
                                        elif f_name.endswith('.pdf'):
                                            reader = PyPDF2.PdfReader(io.BytesIO(f.read()))
                                            for p in reader.pages: texto_extraido += p.extract_text() + "\n"
                                        elif f_name.endswith('.docx'):
                                            doc = docx.Document(io.BytesIO(f.read()))
                                            texto_extraido += "\n".join([para.text for para in doc.paragraphs]) + "\n"
                        
                        if texto_extraido:
                            prompt = f"""Actúa como un experto en desarrollo de software y redes. Eres un profesor virtual en UNIMINUTO.
Evalúa esta entrega basándote en el ENUNCIADO y la RÚBRICA.

ENUNCIADO: {st.session_state.enunciado}
RÚBRICA: {rubrica_texto}

REGLAS OBLIGATORIAS:
- ESCALA DE CALIFICACIÓN: La nota OBLIGATORIAMENTE debe ser un número decimal entre 0.0 y 5.0 (ejemplo: 4.5, 3.2, 5.0). NUNCA uses escalas de 10 o 100.
- NO uses emojis, ni viñetas, ni íconos.
- PROHIBICIÓN ABSOLUTA DE VOCABULARIO: BAJO NINGUNA CIRCUNSTANCIA uses las palabras "crucial" o "clave" en tu respuesta. Cámbialas por "fundamental" o "importante".
- Escribe en segunda persona ('tú').
- p1 (Logros): Un párrafo destacando lo bueno.
- p2 (Mejoras): Un párrafo con áreas de oportunidad. NUNCA sugieras un reenvío del trabajo.
- p3 (Material): Un párrafo con referencias bibliográficas reales (1 en español, 1 en inglés).

ENTREGA DEL ESTUDIANTE:
{texto_extraido[:8000]}

RESPONDE ÚNICAMENTE CON UN JSON VÁLIDO CON LAS CLAVES: "nota" (número decimal entre 0 y 5), "p1", "p2", "p3" (textos)."""

                            try:
                                respuesta = client.chat.completions.create(
                                    model="llama-3.3-70b-versatile",
                                    messages=[{"role": "user", "content": prompt}],
                                    response_format={"type": "json_object"},
                                    temperature=0.2
                                )
                                
                                resultado = json.loads(respuesta.choices[0].message.content)
                                
                                html_final = st.session_state.plantilla.replace('REEMPLAZO_P1', resultado.get('p1', ''))
                                html_final = html_final.replace('REEMPLAZO_P2', resultado.get('p2', ''))
                                html_final = html_final.replace('REEMPLAZO_P3', resultado.get('p3', ''))
                                
                                st.session_state['estudiantes_evaluados'].append({
                                    'nombre': nombre_estudiante,
                                    'student_id': student_id,
                                    'nota': float(resultado.get('nota', 0)),
                                    'html_final': html_final
                                })
                                    
                            except Exception as e:
                                st.error(f"Error procesando a {nombre_estudiante}: {e}")
                        
                        barra_progreso.progress((idx + 1) / total_estudiantes)
                    
                    st.success("✅ Borradores generados. Por favor, revisa las notas abajo antes de enviar.")

# 6. MÓDULO DE VISTA PREVIA Y SINCRONIZACIÓN FINAL
if st.session_state.get('estudiantes_evaluados'):
    st.divider()
    st.subheader("👀 Vista Previa de Calificaciones (Pendientes de Envío)")
    
    for est in st.session_state['estudiantes_evaluados']:
        if est['nota'] < 3.5:
            st.warning(f"⚠️ ATENCIÓN: {est['nombre']} obtuvo una nota de {est['nota']}. Requiere revisión.")
            
        with st.expander(f"🧑‍🎓 {est['nombre']} - Nota Asignada: {est['nota']}"):
            st.markdown("**Previsualización del comentario (HTML renderizado):**")
            components.html(est['html_final'], height=250, scrolling=True)

    st.divider()
    st.subheader("🚀 Paso Final: Sincronización con Canvas")
    st.info(f"Tienes {len(st.session_state['estudiantes_evaluados'])} calificaciones listas para enviar.")
    
    if st.button("📤 APROBAR Y SUBIR TODAS LAS NOTAS A CANVAS", type="primary"):
        barra_envio = st.progress(0)
        total_envio = len(st.session_state['estudiantes_evaluados'])
        errores = 0
        
        for idx_envio, est in enumerate(st.session_state['estudiantes_evaluados']):
            exito = enviar_nota_canvas(canvas_domain, canvas_token, curso_id, actividad_id, est['student_id'], est['nota'], est['html_final'])
            if not exito:
                st.error(f"❌ Fallo al enviar la nota de {est['nombre']}.")
                errores += 1
            barra_envio.progress((idx_envio + 1) / total_envio)
            
        if errores == 0:
            st.balloons()
            st.success("¡Sincronización completada! Todas las notas y comentarios se enviaron exitosamente a Canvas.")
            st.session_state['estudiantes_evaluados'] = []
        else:
            st.warning(f"Se enviaron las notas, pero hubo {errores} errores. Revisa los mensajes arriba.")
