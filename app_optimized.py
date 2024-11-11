import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import re
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import io
import pytz
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader

# Page config
st.set_page_config(
    page_title="Análisis de Equipamiento FHOS",
    page_icon="🔧",
    layout="wide"
)

@st.cache_resource
def load_auth_config():
    """Load authentication configuration"""
    with open('config.yaml') as file:
        return yaml.load(file, Loader=SafeLoader)

@st.cache_data
def convert_excel_date(excel_date):
    """Convert Excel date serial number to datetime"""
    try:
        if isinstance(excel_date, (int, float)) or (isinstance(excel_date, str) and excel_date.isdigit()):
            return pd.Timestamp('1899-12-30') + pd.Timedelta(days=float(excel_date))
        return pd.NaT
    except:
        return pd.NaT

@st.cache_data
def load_data():
    """Load and preprocess data with error handling"""
    try:
        # Load all dataframes
        handpiece_df = pd.read_csv('data_311024/handpieces.csv')
        drv_df = pd.read_csv('data_311024/datos_drv_it.csv')
        treatments_df = pd.read_csv('data_311024/treatments.csv')
        treatments_id_df = pd.read_csv('data_311024/treatments_id.csv')

        # Convert fecha_corte without debug information
        drv_df['fecha_corte'] = drv_df['fecha_corte'].apply(convert_excel_date)

        return handpiece_df, drv_df, treatments_df, treatments_id_df
    except Exception as e:
        st.error(f"Error loading data: {str(e)}")
        return None, None, None, None

@st.cache_data
def get_suggested_cutoff_date(_drv_df, din):
    """Get suggested cutoff date from drv_df for specific DIN"""
    try:
        fecha_corte = _drv_df[_drv_df['din'] == din]['fecha_corte'].iloc[0]
        fecha_corte = pd.to_datetime(fecha_corte)

        # Set timezone to UTC if naive
        if fecha_corte.tz is None:
            fecha_corte = fecha_corte.tz_localize('UTC')

        min_date = pd.Timestamp('2023-01-01', tz='UTC')

        if pd.isna(fecha_corte) or fecha_corte < min_date:
            return min_date

        return fecha_corte
    except (IndexError, KeyError):
        return pd.Timestamp('2023-01-01', tz='UTC')

@st.cache_data
def format_datetime_for_display(dt):
    """Format datetime for display, handling timezone conversion"""
    if pd.isna(dt):
        return ""
    if not isinstance(dt, pd.Timestamp):
        dt = pd.to_datetime(dt)
    if dt.tz is None:
        dt = dt.tz_localize('UTC')
    return dt.tz_convert('Europe/Madrid').strftime('%d/%m/%y')

@st.cache_data
def process_data(_handpiece_df, _treatments_df, treatments_id_df, din, cutoff_date):
    """
    Process and filter handpiece and treatment data

    Parameters:
        _handpiece_df: DataFrame with handpiece data
        _treatments_df: DataFrame with treatments data
        treatments_id_df: DataFrame with treatment IDs
        din: String with equipment DIN
        cutoff_date: Datetime with cutoff date
    """
    # Create copies to avoid modifying original data
    handpiece_df = _handpiece_df.copy()
    treatments_df = _treatments_df.copy()

    # Convert cutoff_date to UTC timezone if not already
    if cutoff_date.tz is None:
        cutoff_date = pd.to_datetime(cutoff_date).tz_localize('UTC')

    # Process handpiece data
    handpiece_df['pulse_count'] = (handpiece_df['pulse_count'] / 3).round(0).astype(int)

    # Drop unnecessary columns
    handpiece_df.drop(columns=[
        'use_count', 'prod_date', 'pulse_energy', 'burst_energy',
        'activation_energy', 'modulation_energy', 'rn'
    ], inplace=True)

    # Rename count columns
    handpiece_df.rename(columns={
        'pulse_count': 'pulso',
        'burst_count': 'rafaga',
        'activation_count': 'activacion',
        'modulation_count': 'modulacion'
    }, inplace=True)

    # Calculate vida_util percentage
    handpiece_df['vida_util'] = handpiece_df.apply(
        lambda row: calculate_vida_util(row, row['handpiece_id']),
        axis=1
    )

    # Process handpiece IDs
    handpiece_df['handpiece_id'] = handpiece_df['handpiece_id'].apply(
        lambda x: 'F.F.' if re.search(r'2\d$', str(x))
        else 'M.F.' if re.search(r'1\d$', str(x))
        else 'Manguera_no_identificada'
    )

    # Rename remaining columns
    handpiece_df.rename(columns={
        'created_at': 'fecha_uso',
        'handpiece_id': 'tipo_manipulo',
        'serial_number': 'numero_serie'
    }, inplace=True)

    # Filter handpieces by DIN and process dates
    filtered_handpiece_df = process_handpiece_dates(
        handpiece_df[handpiece_df['din'] == din].copy(),
        cutoff_date
    )

    # Process treatments
    filtered_treatments_df = process_treatments(
        treatments_df, treatments_id_df, din, cutoff_date
    )

    return filtered_handpiece_df, filtered_treatments_df

@st.cache_data
def calculate_vida_util(row, handpiece_id):
    """Calculate vida_util percentage for a handpiece"""
    try:
        if re.search(r'1\d$', str(handpiece_id)):
            # M.F. calculation
            total = 4000000
            used = ((row['pulso'] * 20) +
                    (row['rafaga'] * 1) +
                    (row['activacion'] + row['modulacion']))
        elif re.search(r'2\d$', str(handpiece_id)):
            # F.F. calculation
            total = 2000000
            used = ((row['pulso'] * 10) +
                    (row['rafaga'] * 1) +
                    ((row['activacion'] + row['modulacion']) * 0.5))
        else:
            return 'Manguera_no_identificada'

        remaining = total - used
        if remaining <= 0:
            return '0%'
        return f"{(remaining / total * 100):.1f}%"
    except Exception:
        return 'Error'

@st.cache_data
def process_handpiece_dates(filtered_handpiece_df, cutoff_date):
    """Process dates for handpiece data"""
    try:
        filtered_handpiece_df['fecha_uso'] = pd.to_datetime(filtered_handpiece_df['fecha_uso'])
        if filtered_handpiece_df['fecha_uso'].dt.tz is None:
            filtered_handpiece_df['fecha_uso'] = filtered_handpiece_df['fecha_uso'].dt.tz_localize('UTC')

        # Filter by date and sort
        filtered_handpiece_df = filtered_handpiece_df[
            filtered_handpiece_df['fecha_uso'] >= cutoff_date
            ].sort_values(by='fecha_uso', ascending=False).reset_index(drop=True)

        # Add status
        today = pd.Timestamp.now(tz='UTC')
        filtered_handpiece_df['estado'] = filtered_handpiece_df['fecha_uso'].apply(
            lambda x: 'ACTIVO' if (today - x).days < 30 else 'INACTIVO'
        )

        # Select and order columns
        return filtered_handpiece_df[[
            'fecha_uso', 'estado', 'din', 'tipo_manipulo', 'numero_serie',
            'vida_util', 'pulso', 'rafaga', 'activacion',
            'modulacion'
        ]]
    except Exception as e:
        st.error(f"Error processing handpiece dates: {str(e)}")
        return pd.DataFrame()

@st.cache_data
def process_treatments(_treatments_df, treatments_id_df, din, cutoff_date):
    """Process treatments data"""
    try:
        # Merge treatment data
        treatments_df = _treatments_df.merge(
            treatments_id_df,
            how='left',
            left_on='code',
            right_on='Treatment_ID'
        )

        # Fill default values
        treatments_df = treatments_df.assign(
            Tipo=treatments_df['Tipo'].fillna('FHOS'),
            Subprograma=treatments_df['Subprograma'].fillna('FHOS genérico'),
            PVP=treatments_df['PVP'].fillna(60),
            Secuencia=treatments_df['Secuencia'].fillna(1.0)
        )

        # Filter by DIN
        filtered_treatments_df = treatments_df[treatments_df['din'] == din].copy()

        # Process dates
        filtered_treatments_df['reported_at'] = pd.to_datetime(filtered_treatments_df['reported_at'])
        if filtered_treatments_df['reported_at'].dt.tz is None:
            filtered_treatments_df['reported_at'] = filtered_treatments_df['reported_at'].dt.tz_localize('UTC')

        # Filter by date
        filtered_treatments_df = filtered_treatments_df[
            filtered_treatments_df['reported_at'] >= cutoff_date
            ].reset_index(drop=True)

        return filtered_treatments_df

    except Exception as e:
        st.error(f"Error processing treatments: {str(e)}")
        return pd.DataFrame()

@st.cache_data
def create_treatment_summary(filtered_treatments_df):
    """
    Create summary of treatments with overall statistics

    Parameters:
        filtered_treatments_df: DataFrame with filtered treatment data
    """
    try:
        resumen_tratamientos = filtered_treatments_df[filtered_treatments_df['Secuencia'] == 1.0].groupby('Tipo').agg(
            Cantidad=('Tipo', 'count'),
            PVP=('PVP', 'sum'),
        ).sort_values(by='Cantidad', ascending=False).reset_index()

        total_cantidad = resumen_tratamientos['Cantidad'].sum()
        total_pvp = resumen_tratamientos['PVP'].sum()

        resumen_tratamientos['% de Tratamientos'] = (resumen_tratamientos['Cantidad'] / total_cantidad * 100).round(2)
        resumen_tratamientos['% de Ingresos'] = (resumen_tratamientos['PVP'] / total_pvp * 100).round(2)

        return resumen_tratamientos
    except Exception as e:
        st.error(f"Error creating treatment summary: {str(e)}")
        return pd.DataFrame()

@st.cache_data
def create_program_summary(filtered_treatments_df):
    """
    Create summary of programs by Subtipo

    Parameters:
        filtered_treatments_df: DataFrame with filtered treatment data
    """
    try:
        resumen_subtipo = filtered_treatments_df[filtered_treatments_df['Secuencia'] == 1.0].groupby('Subtipo').agg(
            Cantidad=('Subtipo', 'count'),
            PVP=('PVP', 'sum'),
        ).sort_values(by='Cantidad', ascending=False).reset_index()

        total_cantidad = resumen_subtipo['Cantidad'].sum()
        total_pvp = resumen_subtipo['PVP'].sum()

        resumen_subtipo['% de Tratamientos'] = (resumen_subtipo['Cantidad'] / total_cantidad * 100).round(2)
        resumen_subtipo['% de Ingresos'] = (resumen_subtipo['PVP'] / total_pvp * 100).round(2)

        return resumen_subtipo
    except Exception as e:
        st.error(f"Error creating program summary: {str(e)}")
        return pd.DataFrame()

@st.cache_data
def create_subprogram_summary(filtered_treatments_df):
    """
    Create summary of subprograms with statistics

    Parameters:
        filtered_treatments_df: DataFrame with filtered treatment data
    """
    try:
        resumen_subprogramas = filtered_treatments_df[filtered_treatments_df['Secuencia'] == 1.0].groupby('Subprograma').agg(
            Cantidad=('Subprograma', 'count'),
            PVP=('PVP', 'sum'),
        ).sort_values(by='Cantidad', ascending=False).reset_index()

        total_cantidad = resumen_subprogramas['Cantidad'].sum()
        total_pvp = resumen_subprogramas['PVP'].sum()

        resumen_subprogramas['% de Tratamientos'] = (resumen_subprogramas['Cantidad'] / total_cantidad * 100).round(2)
        resumen_subprogramas['% de Ingresos'] = (resumen_subprogramas['PVP'] / total_pvp * 100).round(2)

        return resumen_subprogramas
    except Exception as e:
        st.error(f"Error creating subprogram summary: {str(e)}")
        return pd.DataFrame()

@st.cache_data
def prepare_chart_data(summary_df, value_column='Cantidad', names_column='Tipo'):
    """
    Prepare data for pie charts

    Parameters:
        summary_df: DataFrame with summary data
        value_column: Column to use for values
        names_column: Column to use for names
    """
    try:
        if summary_df.empty:
            return None

        return px.pie(
            summary_df,
            values=value_column,
            names=names_column,
            title=f'Distribución de {value_column}'
        )
    except Exception as e:
        st.error(f"Error preparing chart data: {str(e)}")
        return None
def generate_pdf_summary(filtered_handpiece_df, treatment_summary, program_summary, subprogram_summary, din, cutoff_date):
    """
    Generate comprehensive PDF summary report

    Parameters:
        filtered_handpiece_df: DataFrame with handpiece data
        treatment_summary: DataFrame with treatment summary
        program_summary: DataFrame with program summary
        subprogram_summary: DataFrame with subprogram summary
        din: String with equipment DIN
        cutoff_date: Datetime with cutoff date
    """
    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
        story = []
        styles = getSampleStyleSheet()

        # Create custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            spaceAfter=30
        )

        # Add title section
        story.extend([
            Paragraph("Análisis de Equipamiento FHOS", title_style),
            Paragraph(f"DIN: {din}", styles['Heading2']),
            Paragraph(f"Fecha de corte: {format_datetime_for_display(cutoff_date)}", styles['Heading2']),
            Spacer(1, 12)
        ])

        # Add main explanatory text
        story.append(Paragraph("""
            Este informe contiene datos de los equipos RAMASON FHOS desde el 1 de enero de 2023 
            hasta el 31 de octubre de 2024. Estos datos son más precisos conforme más actualizados 
            sean ya que dichos equipos han tenido diversas actualizaciones que han mejorado la 
            categorización, precisión y optimización de dichos datos.
        """, styles['Normal']))

        # Handpiece Analysis Section
        story.extend([
            Spacer(1, 12),
            Paragraph("Análisis de Manípulos", styles['Heading2']),
            Paragraph("""
                A continuación aparecerán todos los manípulos que han sido conectados a tu equipo. 
                Si ves muchos manípulos conectados en un periodo corto de fechas esto se debe a que 
                un técnico de servicio técnico ha conectado diversos manípulos a el equipo para realizar 
                pruebas de conexión y potencia, comparando el rendimiento de tus manípulos a otros 
                similares para diagnosticar si el error es de manípulo o del equipo. Los primeros dos 
                manípulos que aparecen serán los de tu equipo en este caso. La "fecha_uso" es la última fecha en la
                que el equipo reportó ese manípulo por WiFi al sistema en la nube. El "estado" se fija en "ACTIVO" si el 
                manípulo ha sido usado en el último mes desde la fecha del informe.
            """, styles['Normal']),
            Spacer(1, 12)
        ])

        # Create table style
        table_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('FONTSIZE', (0, 1), (-1, -1), 7),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ])

        # Add handpiece table
        display_columns = [
            'fecha_uso', 'estado', 'tipo_manipulo', 'numero_serie', 'vida_util',
            'pulso', 'rafaga', 'activacion', 'modulacion'
        ]
        handpiece_data = filtered_handpiece_df[display_columns].copy()
        handpiece_data['fecha_uso'] = handpiece_data['fecha_uso'].apply(format_datetime_for_display)
        handpiece_table_data = [handpiece_data.columns.tolist()] + handpiece_data.values.tolist()
        handpiece_table = Table(handpiece_table_data)
        handpiece_table.setStyle(table_style)
        story.append(handpiece_table)

        # Treatment Summary Section
        if not treatment_summary.empty:
            story.extend([
                Spacer(1, 20),
                Paragraph("Resumen de Tratamientos", styles['Heading2']),
                Spacer(1, 12),
                Paragraph("""
                    Se fija un precio de 25€ por depilación de media, de 60€ por tratamiento FHOS de media 
                    y de 50€ por tratamientos de FHOS Carbón Activo. En el caso de FHOS solo se computa 
                    la primera secuencia o subprograma de un tratamiento (ej. Activación) no la continuación 
                    para no inflar los datos (ej. Estimulación no computaría).
                """, styles['Normal']),
                Spacer(1, 12)
            ])

            treatment_data = [treatment_summary.columns.tolist()] + treatment_summary.values.tolist()
            treatment_table = Table(treatment_data)
            treatment_table.setStyle(table_style)
            story.append(treatment_table)

            # Program Summary Section
            story.extend([
                Spacer(1, 20),
                Paragraph("Resumen por Programa", styles['Heading2']),
                Spacer(1, 12)
            ])

            program_data = [program_summary.columns.tolist()] + program_summary.values.tolist()
            program_table = Table(program_data)
            program_table.setStyle(table_style)
            story.append(program_table)

            # Subprogram Summary Section
            story.extend([
                Spacer(1, 20),
                Paragraph("Resumen por Subprogramas", styles['Heading2']),
                Spacer(1, 12)
            ])

            subprogram_data = [subprogram_summary.columns.tolist()] + subprogram_summary.values.tolist()
            subprogram_table = Table(subprogram_data)
            subprogram_table.setStyle(table_style)
            story.append(subprogram_table)

        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer

    except Exception as e:
        st.error(f"Error generating PDF summary: {str(e)}")
        return None

def generate_detailed_pdf(filtered_treatments_df, din, cutoff_date):
    """
    Generate detailed PDF report of treatments

    Parameters:
        filtered_treatments_df: DataFrame with treatment data
        din: String with equipment DIN
        cutoff_date: Datetime with cutoff date
    """
    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=20, leftMargin=20, topMargin=30, bottomMargin=30)
        story = []
        styles = getSampleStyleSheet()

        # Title section
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            spaceAfter=30
        )
        story.extend([
            Paragraph("Detalle de Tratamientos", title_style),
            Paragraph(f"DIN: {din}", styles['Heading2']),
            Paragraph(f"Fecha de corte: {format_datetime_for_display(cutoff_date)}", styles['Heading2']),
            Spacer(1, 12)
        ])

        # Explanatory text
        story.append(Paragraph("""
            Esta tabla resume los tratamientos realizados con el equipo. Estos datos son más precisos 
            conforme más actuales sean ya que dichos equipos han tenido diversas actualizaciones desde 
            el 1 de enero de 2023 que han mejorado la categorización, precisión y optimización de dichos 
            datos. Estos datos tendrán más y más información conforme se vaya actualizando el equipo. 
            Si en un tratamiento sales del mismo para, por ejemplo, cambiar el fototipo o algún otro 
            parámetro definido para el mismo, dicho tratamiento se volverá a iniciar y a día de hoy 
            contabilizará dos veces en la tabla de tratamientos realizados. Estos datos cubren el rango 
            de fechas desde la "Fecha de corte" hasta el 31/10/2024. Los tratamientos de FHOS tienen múltiples
            subprogramas que se detallan en la tabla como tratamientos individuales (los distintos pasos: activación,
            estimulación, etc.).
        """, styles['Normal']))

        story.append(Spacer(1, 12))

        # Prepare treatment data
        treatments_df_export = filtered_treatments_df[['reported_at', 'code', 'Tipo', 'Subprograma', 'duration']].copy()
        treatments_df_export['reported_at'] = treatments_df_export['reported_at'].apply(format_datetime_for_display)
        treatments_df_export['duration'] = (treatments_df_export['duration'] / 60000).round(2)  # Convert to minutes

        # Create table
        treatments_data = [treatments_df_export.columns.tolist()] + treatments_df_export.values.tolist()
        table_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ])

        treatments_table = Table(treatments_data, repeatRows=1)
        treatments_table.setStyle(table_style)
        story.append(treatments_table)

        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer

    except Exception as e:
        st.error(f"Error generating detailed PDF: {str(e)}")
        return None

def init_auth():
    """Initialize authentication"""
    config = load_auth_config()
    return stauth.Authenticate(
        config['credentials'],
        config['cookie']['name'],
        config['cookie']['key'],
        config['cookie']['expiry_days']
    )

def main():
    """Main application function"""
    st.title("🔧 Herramienta de análisis RAMASON")

    # Initialize session state
    if 'authentication_status' not in st.session_state:
        st.session_state['authentication_status'] = None
    if 'name' not in st.session_state:
        st.session_state['name'] = None
    if 'username' not in st.session_state:
        st.session_state['username'] = None

    # Initialize authenticator
    authenticator = init_auth()

    # Attempt authentication
    try:
        login_result = authenticator.login(key='login')
        if login_result is not None:
            name, authentication_status, username = login_result
            st.session_state['name'] = name
            st.session_state['authentication_status'] = authentication_status
            st.session_state['username'] = username
        else:
            authentication_status = None
    except Exception as e:
        st.error(f"Error de autenticación: {str(e)}")
        return

    if st.session_state['authentication_status']:
        # Show logout button and welcome message
        authenticator.logout('Cerrar sesión', 'sidebar')
        st.sidebar.success(f'Bienvenido/a {st.session_state["name"]}')

        # Load data
        handpiece_df, drv_df, treatments_df, treatments_id_df = load_data()

        if all(df is not None for df in [handpiece_df, drv_df, treatments_df, treatments_id_df]):
            # Sidebar configuration
            st.sidebar.title("Configuración")

            # DIN input
            din = st.sidebar.text_input(
                "DIN del equipo",
                value="CM-A30-000000",
                help="Introduce el DIN del equipo a analizar"
            )

            # Date handling
            suggested_date = get_suggested_cutoff_date(drv_df, din)
            if suggested_date.tz is None:
                suggested_date = suggested_date.tz_localize('UTC')

            st.sidebar.info(f"Fecha de corte sugerida: {format_datetime_for_display(suggested_date)}")

            min_date = pd.Timestamp('2023-01-01', tz='UTC')
            default_date = max(suggested_date, min_date)
            default_date_naive = default_date.tz_localize(None).date()
            min_date_naive = min_date.tz_localize(None).date()

            cutoff_date = st.sidebar.date_input(
                "Fecha de corte",
                value=default_date_naive,
                min_value=min_date_naive,
                max_value=datetime.now().date(),
                help="Selecciona la fecha de corte para el análisis"
            )

            cutoff_date = pd.Timestamp(cutoff_date).tz_localize('UTC')

            # Analyze button
            analyze_button = st.sidebar.button("Analizar", type="primary")

            # Footer
            st.sidebar.markdown("---")
            st.sidebar.text("Desarrollado con 🖤 por Belvi.")
            st.sidebar.text("Copyright © 2024 Belvi Digital S.L.")

            # Main content - only show when analyze button is clicked
            if analyze_button:
                st.title("Análisis de equipamiento FHOS")
                st.write(f"DIN: {din}")
                st.write(f"Fecha de corte: {format_datetime_for_display(cutoff_date)}")

                # Main description
                st.markdown("""
                Este informe contiene datos de los equipos RAMASON FHOS (ej. RAMASON FHOS PROCYON) 
                desde el 1 de enero de 2023 hasta el 31 de octubre de 2024. Estos datos son más precisos 
                conforme más actualizados sean ya que dichos equipos han tenido diversas actualizaciones 
                desde el 1 de enero de 2023 que han mejorado la categorización, precisión y optimización 
                de dichos datos.
                """)

                # Process data
                filtered_handpiece_df, filtered_treatments_df = process_data(
                    handpiece_df, treatments_df, treatments_id_df, din, cutoff_date
                )

                # Handpiece Analysis
                st.subheader("Análisis de manípulos")
                st.markdown("""
                A continuación aparecerán todos los manípulos que han sido conectados a tu equipo. 
                Si ves muchos manípulos conectados en un periodo corto de fechas esto se debe a que 
                un técnico de servicio técnico ha conectado diversos manípulos a el equipo para realizar 
                pruebas de conexión y potencia, comparando el rendimiento de tus manípulos a otros 
                similares para diagnosticar si el error es de manípulo o del equipo. Los primeros dos 
                manípulos que aparecen serán los de tu equipo en este caso. La "fecha_uso" es la última fecha en la
                que el equipo reportó ese manípulo por WiFi al sistema en la nube. El "estado" se fija en "ACTIVO" si el 
                manípulo ha sido usado en el último mes desde la fecha del informe."
                """)

                st.dataframe(filtered_handpiece_df, use_container_width=True)

                # Treatment Analysis
                if not filtered_treatments_df.empty:
                    st.subheader("Análisis de tratamientos realizados")

                    # Charts
                    col1, col2 = st.columns(2)
                    with col1:
                        treatment_summary = create_treatment_summary(filtered_treatments_df)
                        fig1 = prepare_chart_data(treatment_summary, 'Cantidad', 'Tipo')
                        if fig1:
                            st.plotly_chart(fig1, use_container_width=True)

                    with col2:
                        fig2 = prepare_chart_data(treatment_summary, 'PVP', 'Tipo')
                        if fig2:
                            st.plotly_chart(fig2, use_container_width=True)

                    # Summaries
                    st.subheader("Detalles de Tratamientos")
                    st.info("""Se fija un precio de 25€ por depilación de media, de 60€ por tratamiento FHOS de media 
                    y de 50€ por tratamientos de FHOS Carbón Activo. En el caso de FHOS solo se computa 
                    la primera secuencia o subprograma de un tratamiento (ej. Activación) no la continuación 
                    para no inflar los datos (ej. Estimulación no computaría).""")
                    st.dataframe(treatment_summary, use_container_width=True)

                    st.subheader("Resumen por Programa")
                    program_summary = create_program_summary(filtered_treatments_df)
                    st.dataframe(program_summary, use_container_width=True)

                    st.subheader("Resumen por Subprogramas")
                    subprogram_summary = create_subprogram_summary(filtered_treatments_df)
                    st.dataframe(subprogram_summary, use_container_width=True)

                    # PDF Download buttons
                    col1, col2 = st.columns(2)
                    with col1:
                        pdf_buffer = generate_pdf_summary(
                            filtered_handpiece_df,
                            treatment_summary,
                            program_summary,
                            subprogram_summary,
                            din,
                            cutoff_date
                        )
                        if pdf_buffer:
                            st.download_button(
                                "Descargar Informe Resumen PDF",
                                pdf_buffer,
                                file_name=f"informe_resumen_{din}.pdf",
                                mime="application/pdf"
                            )

                    with col2:
                        detailed_pdf = generate_detailed_pdf(
                            filtered_treatments_df,
                            din,
                            cutoff_date
                        )
                        if detailed_pdf:
                            st.download_button(
                                "Descargar Informe Tratamientos Detalle PDF",
                                detailed_pdf,
                                file_name=f"informe_detallado_{din}.pdf",
                                mime="application/pdf"
                            )
                else:
                    st.warning("No se encontraron tratamientos para el período seleccionado")

    elif st.session_state['authentication_status'] == False:
        st.error('Usuario o contraseña incorrectos')
    else:
        st.warning('Por favor, introduzca su usuario y contraseña')

if __name__ == "__main__":
    main()