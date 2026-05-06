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
import time

# 1. Configuración Inicial de la Aplicación
st.set_page_config(page_title="AeroGrade Pro - UNIMINUTO", layout="wide")

# Inicializar la memoria de la sesión si no existe
if 'estudiantes_evaluados' not in st.session_state:
    st.session_state['estudiantes_evaluados'] = []

# 2. Función de Envío a Canvas (No consume tokens de IA)
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
# Usamos el secreto de Groq que ya tienes configurado
groq_api_key = st.secrets.get("GROQ_API_KEY", "")
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
        "📝 Enunciado de la Actividad:", 
        placeholder="Pega aquí las instrucciones de la tarea...",
        height=200
    )
with col2:
    st.session_state.plantilla = st.text_area(
        "🖥️ Plantilla HTML de Retroalimentación:", 
        placeholder="Debe contener REEMPLAZO_P1, REEMPLAZO_P2 y REEMPLAZO_P3",
        height=200
    )

# 5. Carga de Insumos Académicos
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
        actividad_seleccionada = st.selectbox("🎯 SELECCIONE LA ACTIVIDAD A CALIFICAR:", ["-- Seleccione una actividad --"] + columnas_actividad)
        
        if actividad_seleccionada != "-- Seleccione una actividad --":
            rubrica_seleccionada = st.selectbox('Selecciona la rúbrica correspondiente:', df_rubricas['Rubric Name'].unique())
            rubrica_texto = df_rubricas[df_rubricas['Rubric Name'] == rubrica_seleccionada].to_csv(index=False)
            
            df_filtrado = df_calificaciones[df_calificaciones['Student'].astype(str).str.strip() != 'Points Possible'].copy()
            
            # Filtro por sección según la actividad
            if 'MA' in actividad_seleccionada:
                df_filtrado = df_filtrado[df_filtrado['Section'].astype(str).str.contains('Actividades', na=False)]
            elif 'MT' in actividad_seleccionada:
                df_filtrado = df_filtrado[df_filtrado['Section'].astype(str).str.contains('Trabajo Final', na=False)]
                
            total_estudiantes = len(df_filtrado)
            
            if total_estudiantes > 0:
                st.write(f"📋 **Estudiantes detectados: {total_estudiantes}**")
                
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    iniciar = st.button('🚀 Iniciar / Continuar Calificación Automática', type="primary")
                with col_btn2:
                    if st.button("🧹 Limpiar memoria (Empezar de cero)"):
                        st.session_state['estudiantes_evaluados'] = []
                        st.rerun()

                if iniciar:
                    if not canvas_token or not groq_api_key:
                        st.error("Faltan credenciales (Canvas Token o Groq API Key en Secrets).")
                        st.stop()
                    
                    client = Groq(api_key=groq_api_key)
                    ids_evaluados = [est['student_id'] for est in st.session_state['estudiantes_evaluados']]
                    
                    barra_progreso = st.progress(0)
                    contenedor_en_vivo = st.container()
                    
                    for idx, (i, row) in enumerate(df_filtrado.iterrows()):
                        nombre_estudiante = row.get('Student', 'Desconocido')
                        student_id = str(int(float(row.get('ID', 0))))
                        nota_actual = row[actividad_seleccionada]
                        
                        # Saltar si ya tiene nota en Canvas o en memoria local
                        if (pd.notna(nota_actual) and str(nota_actual).strip() not in ['', '-']) or student_id in ids_evaluados:
                            barra_progreso.progress((idx + 1) / total_estudiantes)
                            continue
                            
                        # Extracción de archivos
                        texto_extraido = ""
                        if archivo_zip:
                            with zipfile.ZipFile(archivo_zip, 'r') as z:
                                matching_files = [f for f in z.namelist() if student_id in f]
                                for f_name in matching_files:
                                    with z.open(f_name) as f:
                                        ext = f_name.lower()
                                        if ext.endswith(('.java', '.txt', '.sql', '.html', '.py', '.r', '.csv', '.css', '.js', '.xml')):
                                            texto_extraido += f"--- Archivo: {f_name} ---\n"
                                            texto_extraido += f.read().decode('utf-8', errors='ignore') + "\n"
                                        elif ext.endswith('.pdf'):
                                            reader = PyPDF2.PdfReader(io.BytesIO(f.read()))
                                            for p in reader.pages: texto_extraido += p.extract_text() + "\n"
                        
                        if texto_extraido:
                            prompt = f"""Actúa como un profesor experto de UNIMINUTO. 
Evalúa el trabajo basándote en el ENUNCIADO y la RÚBRICA.

ENUNCIADO: {st.session_state.enunciado}
RÚBRICA: {rubrica_texto}

ESTILO DE COMUNICACIÓN OBLIGATORIO:
- Escribe de forma directa y personal, pero PROHIBIDO iniciar frases con "tú", "usted", "él" o "ella". 
- Usa el sujeto tácito (ej: "Hiciste un buen trabajo" en lugar de "Tú hiciste..."). 
- El tono debe ser cercano y empático, como un mentor humano.
- Prohibido usar las palabras "crucial" y "clave". Usa "fundamental" o "importante".

ESTRUCTURA DE RESPUESTA:
- p1 (Logros): Qué se hizo bien.
- p2 (Mejoras): Qué mejorar (sin sugerir reenvíos).
- p3 (Material): Una referencia en español y una en inglés.

ENTREGA DEL ESTUDIANTE:
{texto_extraido[:8000]}

RESPONDE SOLO CON JSON: {{"nota": decimal_0_a_5, "p1": "texto", "p2": "texto", "p3": "texto"}}"""

                            exito_evaluacion = False
                            while not exito_evaluacion:
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
                                        with st.expander(f"🧑‍🎓 {nombre_estudiante} - Nota: {res['nota']}", expanded=False):
                                            components.html(html_f, height=200, scrolling=True)
                                    
                                    exito_evaluacion = True
                                    
                                except Exception as e:
                                    if "429" in str(e) or "rate_limit" in str(e).lower():
                                        # PILOTO AUTOMÁTICO - Temporizador
                                        tiempo_espera = 660 # 11 minutos de seguridad
                                        caja_reloj = contenedor_en_vivo.empty()
                                        for restante in range(tiempo_espera, 0, -1):
                                            m, s = divmod(restante, 60)
                                            caja_reloj.error(f"🛑 Límite de Groq alcanzado. Retomando en **{m:02d}:{s:02d}**. No cierres la pestaña.")
                                            time.sleep(1)
                                        caja_reloj.empty()
                                    else:
                                        with contenedor_en_vivo: st.error(f"Error con {nombre_estudiante}: {e}")
                                        exito_evaluacion = True 
                        
                        barra_progreso.progress((idx + 1) / total_estudiantes)
                    st.success("✅ Evaluación completada. Revisa los borradores y sincroniza abajo.")

# 6. Sincronización Final con Canvas
if st.session_state.get('estudiantes_evaluados'):
    st.divider()
    st.subheader("🚀 Sincronización con Canvas")
    st.info(f"Borradores listos: {len(st.session_state['estudiantes_evaluados'])}")
    
    if st.button("📤 SUBIR TODO A CANVAS AHORA", type="primary"):
        b_envio = st.progress(0)
        total_e = len(st.session_state['estudiantes_evaluados'])
        for idx_e, est in enumerate(st.session_state['estudiantes_evaluados']):
            enviar_nota_canvas(canvas_domain, canvas_token, curso_id, actividad_id, est['student_id'], est['nota'], est['html_final'])
            b_envio.progress((idx_e + 1) / total_e)
        st.balloons()
        st.success("¡Notas y comentarios enviados exitosamente!")
        st.session_state['estudiantes_evaluados'] = []
