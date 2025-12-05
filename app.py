import os
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, desc
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import subprocess
import io

# LIBRERÍAS PARA DOCUMENTOS
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from pypdf import PdfReader, PdfWriter
from pypdf.constants import UserAccessPermissions 

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'clave_segura_unap_2025')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=20)

# --- CONFIGURACIÓN BASE DE DATOS ---
db_uri = os.environ.get('DATABASE_URL')
if not db_uri:
    db_uri = 'postgresql://db_biblioteca_f9zy_user:aKYvfUON1Wql05SGi90GWsFwSuf4NBNS@dpg-d4o8kt2dbo4c73ad2pe0-a.oregon-postgres.render.com/db_biblioteca_f9zy'
if db_uri and db_uri.startswith("postgres://"):
    db_uri = db_uri.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- FUNCIÓN AUXILIAR PARA GUARDAR LOGS ---
def registrar_log(accion, detalle):
    """Guarda un registro de quién hizo qué."""
    try:
        usuario = session.get('admin_user', 'Sistema')
        nuevo_log = Auditoria(usuario=usuario, accion=accion, detalle=detalle)
        db.session.add(nuevo_log)
        db.session.commit()
    except Exception as e:
        print(f"Error al guardar log: {e}")

# --- MODELOS ---
class Auditoria(db.Model):
    __tablename__ = 'auditoria'
    id = db.Column(db.Integer, primary_key=True)
    usuario = db.Column(db.String(50))      # Quién lo hizo
    accion = db.Column(db.String(50))       # CREAR, ELIMINAR, EDITAR
    detalle = db.Column(db.Text)            # Qué hizo exactamente
    fecha = db.Column(db.DateTime, default=datetime.now)

class Alumno(db.Model):
    __tablename__ = 'alumnos'
    id = db.Column(db.Integer, primary_key=True)
    voucher = db.Column(db.String(50), index=True)
    dni = db.Column(db.String(20), index=True)
    fecha_pago = db.Column(db.String(20)) 
    monto = db.Column(db.Float) 
    nombre = db.Column(db.String(150))
    facultad = db.Column(db.String(150))
    escuela = db.Column(db.String(150))
    grado = db.Column(db.String(50))
    fecha_registro = db.Column(db.DateTime, default=datetime.now)
    numero_anual = db.Column(db.Integer)
    anio_registro = db.Column(db.Integer)

class Deudor(db.Model):
    __tablename__ = 'deudores'
    id = db.Column(db.Integer, primary_key=True)
    identificador = db.Column(db.String(50), unique=True)
    motivo = db.Column(db.String(255))
    nombre = db.Column(db.String(150))
    tipo = db.Column(db.String(50))
    facultad = db.Column(db.String(150))
    escuela = db.Column(db.String(150))

class Administrador(db.Model):
    __tablename__ = 'administradores'
    id = db.Column(db.Integer, primary_key=True)
    usuario = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    p_pagos = db.Column(db.Boolean, default=False)
    p_deudores = db.Column(db.Boolean, default=False)
    p_reportes = db.Column(db.Boolean, default=False)
    p_config = db.Column(db.Boolean, default=False)
    p_usuarios = db.Column(db.Boolean, default=False)

class Facultad(db.Model):
    __tablename__ = 'facultades'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), unique=True, nullable=False)
    escuelas = db.relationship('Escuela', backref='facultad_rel', lazy=True)

class Escuela(db.Model):
    __tablename__ = 'escuelas'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), unique=True, nullable=False)
    facultad_id = db.Column(db.Integer, db.ForeignKey('facultades.id'), nullable=False)

class Grado(db.Model):
    __tablename__ = 'grados'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), unique=True, nullable=False)

# --- RUTAS PÚBLICAS ---
@app.route('/api/escuelas/<int:id_facultad>')
def api_get_escuelas(id_facultad):
    escuelas = Escuela.query.filter_by(facultad_id=id_facultad).order_by(Escuela.nombre).all()
    return jsonify([{'id': e.id, 'nombre': e.nombre} for e in escuelas])

@app.route('/', methods=['GET', 'POST'])
def atencion():
    error = None
    alumno_encontrado = None
    if request.method == 'POST':
        voucher = request.form.get('voucher', '').strip()
        dni = request.form.get('dni', '').strip()
        fecha = request.form.get('fecha', '').strip()

        deudor = Deudor.query.filter((Deudor.identificador==dni) | (Deudor.identificador==voucher)).first()
        if deudor:
            error = f"🚫 ACCESO DENEGADO: {deudor.tipo} bloqueado por '{deudor.motivo}'."
        else:
            alumno = Alumno.query.filter_by(voucher=voucher, dni=dni, fecha_pago=fecha).first()
            if alumno:
                if alumno.monto and alumno.monto < 57.50:
                    error = "❌ Error: El monto pagado es insuficiente (Menor a S/ 57.50)."
                elif alumno.nombre:
                    alumno_encontrado = alumno
                else:
                    flash("✅ Pago validado. Complete sus datos.")
                    return redirect(url_for('completar_datos', id=alumno.id))
            else:
                error = "❌ Error: Datos incorrectos o pago no registrado."
    return render_template('atencion.html', error=error, alumno=alumno_encontrado)

@app.route('/login', methods=['GET', 'POST'])
def login_admin():
    if request.method == 'POST':
        usuario = request.form['usuario']
        password_ingresado = request.form['password']
        admin = Administrador.query.filter_by(usuario=usuario).first()
        if admin and check_password_hash(admin.password, password_ingresado):
            session['admin_logged_in'] = True
            session['admin_user'] = admin.usuario
            session.permanent = True
            
            session['p_pagos'] = admin.p_pagos
            session['p_deudores'] = admin.p_deudores
            session['p_reportes'] = admin.p_reportes
            session['p_config'] = admin.p_config
            session['p_usuarios'] = admin.p_usuarios
            
            registrar_log("LOGIN", "Inicio de sesión exitoso.") # LOG
            return redirect(url_for('admin'))
        else:
            flash("❌ Usuario o contraseña incorrectos")
    return render_template('login_admin.html')

@app.route('/logout')
def logout():
    registrar_log("LOGOUT", "Cierre de sesión.") # LOG
    session.clear()
    return redirect(url_for('login_admin'))

# --- ADMIN PANEL ---
@app.route('/admin', methods=['GET'])
def admin():
    if not session.get('admin_logged_in'): return redirect(url_for('login_admin'))
    t_vouchers = Alumno.query.count()
    t_emitidas = Alumno.query.filter(Alumno.nombre != None).count()
    t_pendientes = t_vouchers - t_emitidas
    t_deudores = Deudor.query.count()
    
    q_fac = db.session.query(Alumno.facultad, func.count(Alumno.id)).filter(Alumno.facultad != None).group_by(Alumno.facultad).all()
    l_fac, d_fac = ([row[0] for row in q_fac], [row[1] for row in q_fac])
    
    q_esc = db.session.query(Alumno.escuela, func.count(Alumno.id)).filter(Alumno.escuela != None).group_by(Alumno.escuela).order_by(func.count(Alumno.id).desc()).limit(10).all()
    l_esc, d_esc = ([row[0] for row in q_esc], [row[1] for row in q_esc])
    
    q_gra = db.session.query(Alumno.grado, func.count(Alumno.id)).filter(Alumno.grado != None).group_by(Alumno.grado).all()
    l_gra, d_gra = ([row[0] for row in q_gra], [row[1] for row in q_gra])
    
    rep = db.session.query(Alumno.dni, Alumno.nombre, func.count(Alumno.id).label('total')).filter(Alumno.nombre != None).group_by(Alumno.dni, Alumno.nombre).having(func.count(Alumno.id) > 1).order_by(desc('total')).limit(10).all()

    return render_template('admin.html', usuario=session.get('admin_user'),
                           t_vouchers=t_vouchers, t_emitidas=t_emitidas, t_pendientes=t_pendientes, t_deudores=t_deudores,
                           l_facultades=l_fac, d_facultades=d_fac, l_escuelas=l_esc, d_escuelas=d_esc, l_grados=l_gra, d_grados=d_gra, repetidos=rep)

# --- NUEVA RUTA: HISTORIAL DE CAMBIOS ---
@app.route('/admin/auditoria')
def admin_auditoria():
    if not session.get('admin_logged_in') or not session.get('p_usuarios'): 
        flash("⛔ Solo Super Admin.")
        return redirect(url_for('admin'))
    
    # Traemos los últimos 500 registros ordenados por fecha
    logs = Auditoria.query.order_by(Auditoria.id.desc()).limit(500).all()
    return render_template('admin_auditoria.html', logs=logs)

@app.route('/admin/backup')
def admin_backup():
    if not session.get('admin_logged_in') or not session.get('p_usuarios'): 
        return redirect(url_for('admin'))
    
    registrar_log("BACKUP", "Descargó copia de seguridad del sistema.") # LOG
    
    try:
        db_url = app.config['SQLALCHEMY_DATABASE_URI']
        filename_sql = f"backup_{datetime.now().strftime('%Y%m%d_%H%M')}.sql"
        command = f'pg_dump "{db_url}" -f "{filename_sql}"'
        subprocess.run(command, shell=True, check=True)
        return send_file(filename_sql, as_attachment=True, download_name=filename_sql, mimetype='application/sql')
    except Exception as e:
        # Fallback Excel
        output = io.BytesIO()
        writer = pd.ExcelWriter(output, engine='openpyxl')
        pd.read_sql(Alumno.query.statement, db.session.bind).to_excel(writer, sheet_name='Alumnos', index=False)
        pd.read_sql(Deudor.query.statement, db.session.bind).to_excel(writer, sheet_name='Deudores', index=False)
        pd.read_sql(Auditoria.query.statement, db.session.bind).to_excel(writer, sheet_name='Auditoria', index=False)
        writer.close()
        output.seek(0)
        return send_file(output, as_attachment=True, download_name="Respaldo_Emergencia.xlsx", mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/admin/pagos', methods=['GET', 'POST'])
def admin_pagos():
    if not session.get('admin_logged_in') or not session.get('p_pagos'): return redirect(url_for('admin'))
    if request.method == 'POST':
        if 'voucher_manual' in request.form:
            v = request.form['voucher_manual'].strip()
            d = request.form['dni_manual'].strip()
            f = request.form['fecha_manual'].strip()
            try:
                m_float = float(request.form['monto_manual'].strip())
                if m_float < 57.50:
                    flash(f"⚠️ Error: Monto insuficiente.")
                elif not Alumno.query.filter_by(voucher=v).first():
                    db.session.add(Alumno(voucher=v, dni=d, fecha_pago=f, monto=m_float))
                    db.session.commit()
                    registrar_log("PAGO MANUAL", f"Registró voucher {v} - DNI {d}") # LOG
                    flash(f"✅ Pago registrado: {v}")
                else: flash("⚠️ Voucher ya existe.")
            except: flash("❌ El monto debe ser numérico.")

        elif 'archivo' in request.files:
            file = request.files['archivo']
            if file.filename != '':
                try:
                    if file.filename.endswith('.csv') or file.filename.endswith('.txt'):
                        df = pd.read_csv(file, header=None, dtype=str)
                    else:
                        df = pd.read_excel(file, dtype=str)
                    count = 0
                    for _, row in df.iterrows():
                        if len(row) < 4: continue
                        v, d, f, m = str(row[0]).strip(), str(row[1]).strip(), str(row[2]).strip(), str(row[3]).strip()
                        try:
                            if float(m) >= 57.50 and not Alumno.query.filter_by(voucher=v).first():
                                db.session.add(Alumno(voucher=v, dni=d, fecha_pago=f, monto=float(m)))
                                count += 1
                        except: pass
                    db.session.commit()
                    registrar_log("CARGA MASIVA", f"Subió {count} nuevos pagos.") # LOG
                    flash(f"✅ Carga Masiva: {count} nuevos.")
                except Exception as e: flash(f"Error: {e}")
        return redirect(url_for('admin_pagos'))
    pagos = Alumno.query.order_by(Alumno.id.desc()).limit(100).all()
    return render_template('admin_pagos.html', pagos=pagos)

@app.route('/admin/pagos/eliminar/<int:id>')
def admin_eliminar_pago(id):
    if not session.get('admin_logged_in') or not session.get('p_pagos'): return redirect(url_for('admin'))
    p = Alumno.query.get_or_404(id)
    info = f"Voucher: {p.voucher}, DNI: {p.dni}"
    db.session.delete(p)
    db.session.commit()
    registrar_log("ELIMINAR PAGO", f"Eliminó {info}") # LOG
    return redirect(url_for('admin_pagos'))

@app.route('/admin/deudores', methods=['GET', 'POST'])
def admin_deudores():
    if not session.get('admin_logged_in') or not session.get('p_deudores'): return redirect(url_for('admin'))
    if request.method == 'POST':
        identificador = request.form['identificador'].strip()
        nombre = request.form['nombre'].strip().upper()
        if not Deudor.query.filter_by(identificador=identificador).first():
            db.session.add(Deudor(identificador=identificador, nombre=nombre, tipo=request.form['tipo'], facultad=request.form['facultad'], escuela=request.form['escuela'], motivo=request.form['motivo']))
            db.session.commit()
            registrar_log("BLOQUEO", f"Bloqueó a {nombre} ({identificador})") # LOG
            flash(f"🚫 Bloqueado: {nombre}")
        return redirect(url_for('admin_deudores'))
    facs = Facultad.query.order_by(Facultad.nombre).all()
    escs = Escuela.query.order_by(Escuela.nombre).all()
    deudores = Deudor.query.order_by(Deudor.id.desc()).all()
    return render_template('admin_deudores.html', deudores=deudores, facultades=facs, escuelas=escs)

@app.route('/admin/deudores/eliminar/<int:id>')
def admin_eliminar_deudor(id):
    if not session.get('admin_logged_in') or not session.get('p_deudores'): return redirect(url_for('admin'))
    d = Deudor.query.get_or_404(id)
    info = f"{d.nombre} ({d.identificador})"
    db.session.delete(d)
    db.session.commit()
    registrar_log("DESBLOQUEO", f"Desbloqueó a {info}") # LOG
    flash("✅ Desbloqueado.")
    return redirect(url_for('admin_deudores'))

@app.route('/admin/lista')
def admin_lista():
    if not session.get('admin_logged_in') or not session.get('p_reportes'): return redirect(url_for('admin'))
    alumnos = Alumno.query.filter(Alumno.nombre != None).order_by(Alumno.id.desc()).all()
    return render_template('admin_lista.html', alumnos=alumnos, usuario=session.get('admin_user'))

@app.route('/admin/exportar_excel')
def admin_exportar_excel():
    if not session.get('admin_logged_in') or not session.get('p_reportes'): return redirect(url_for('admin'))
    alumnos = Alumno.query.filter(Alumno.nombre != None).order_by(Alumno.id.desc()).all()
    data = [{'N': f"{str(a.numero_anual).zfill(3)}-{a.anio_registro}", 'FECHA': a.fecha_registro.strftime('%d/%m/%Y'), 'VOUCHER': a.voucher, 'DNI': a.dni, 'ALUMNO': a.nombre, 'FACULTAD': a.facultad, 'ESCUELA': a.escuela, 'GRADO': a.grado} for a in alumnos]
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer: df.to_excel(writer, index=False)
    output.seek(0)
    registrar_log("EXPORTAR", "Exportó reporte de constancias a Excel.") # LOG
    return send_file(output, as_attachment=True, download_name=f"Reporte_{datetime.now().strftime('%Y%m%d')}.xlsx", mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/admin/editar_tramite/<int:id>', methods=['GET', 'POST'])
def admin_editar_tramite(id):
    if not session.get('admin_logged_in') or not session.get('p_reportes'): return redirect(url_for('admin'))
    alumno = Alumno.query.get_or_404(id)
    if request.method == 'POST':
        # Guardar valores antiguos para el log
        antiguo = f"{alumno.nombre} | {alumno.facultad}"
        
        alumno.voucher = request.form['voucher'].strip()
        alumno.dni = request.form['dni'].strip()
        alumno.nombre = request.form['nombre'].strip().upper()
        try:
            fac_obj = Facultad.query.get(int(request.form['facultad']))
            esc_obj = Escuela.query.get(int(request.form['escuela']))
            alumno.facultad = fac_obj.nombre
            alumno.escuela = esc_obj.nombre
        except: pass
        alumno.grado = request.form['grado'].strip().upper()
        db.session.commit()
        
        registrar_log("EDICIÓN", f"Editó trámite ID {id}. Antes: {antiguo}. Ahora: {alumno.nombre} | {alumno.facultad}") # LOG
        flash(f"✅ Datos corregidos.")
        return redirect(url_for('admin_lista'))

    facs = Facultad.query.order_by(Facultad.nombre).all()
    grados = Grado.query.all()
    escuela_actual = Escuela.query.filter_by(nombre=alumno.escuela).first()
    id_escuela_actual = escuela_actual.id if escuela_actual else 0
    return render_template('admin_editar_tramite.html', alumno=alumno, facultades=facs, grados=grados, id_escuela_actual=id_escuela_actual)

@app.route('/admin/usuarios', methods=['GET', 'POST'])
def admin_usuarios():
    if not session.get('admin_logged_in') or not session.get('p_usuarios'): return redirect(url_for('admin'))
    if request.method == 'POST':
        u = request.form['usuario'].strip()
        if not Administrador.query.filter_by(usuario=u).first():
            nuevo = Administrador(usuario=u, password=generate_password_hash(request.form['password']), p_pagos='p_pagos' in request.form, p_deudores='p_deudores' in request.form, p_reportes='p_reportes' in request.form, p_config='p_config' in request.form, p_usuarios='p_usuarios' in request.form)
            db.session.add(nuevo)
            db.session.commit()
            registrar_log("USUARIO", f"Creó nuevo administrador: {u}") # LOG
            flash(f"✅ Creado: {u}")
        return redirect(url_for('admin_usuarios'))
    return render_template('admin_usuarios.html', admins=Administrador.query.all(), usuario_actual=session.get('admin_user'))

@app.route('/admin/usuarios/editar/<int:id>', methods=['GET', 'POST'])
def admin_editar_usuario(id):
    if not session.get('admin_logged_in') or not session.get('p_usuarios'): return redirect(url_for('admin'))
    admin_edit = Administrador.query.get_or_404(id)
    if request.method == 'POST':
        admin_edit.usuario = request.form['usuario'].strip()
        if request.form['password'].strip():
            admin_edit.password = generate_password_hash(request.form['password'].strip())
        admin_edit.p_pagos = 'p_pagos' in request.form
        admin_edit.p_deudores = 'p_deudores' in request.form
        admin_edit.p_reportes = 'p_reportes' in request.form
        admin_edit.p_config = 'p_config' in request.form
        admin_edit.p_usuarios = 'p_usuarios' in request.form
        db.session.commit()
        registrar_log("USUARIO", f"Editó permisos/clave de: {admin_edit.usuario}") # LOG
        flash(f"✅ Actualizado.")
        return redirect(url_for('admin_usuarios'))
    return render_template('admin_usuarios_editar.html', admin=admin_edit)

@app.route('/admin/usuarios/eliminar/<int:id>')
def admin_eliminar_usuario(id):
    if not session.get('admin_logged_in') or not session.get('p_usuarios'): return redirect(url_for('admin'))
    adm = Administrador.query.get_or_404(id)
    if adm.usuario != session.get('admin_user'):
        u_name = adm.usuario
        db.session.delete(adm)
        db.session.commit()
        registrar_log("USUARIO", f"Eliminó administrador: {u_name}") # LOG
    return redirect(url_for('admin_usuarios'))

# --- CONFIGURACIONES (LOGS SIMPLIFICADOS) ---
@app.route('/admin/facultades', methods=['GET', 'POST'])
def admin_facultades():
    if not session.get('admin_logged_in') or not session.get('p_config'): return redirect(url_for('admin'))
    if request.method == 'POST':
        n = request.form['nombre'].strip().upper()
        if not Facultad.query.filter_by(nombre=n).first():
            db.session.add(Facultad(nombre=n))
            db.session.commit()
            registrar_log("CONFIG", f"Creó facultad: {n}")
    return render_template('admin_facultades.html', facultades=Facultad.query.order_by(Facultad.nombre).all())

@app.route('/admin/facultades/eliminar/<int:id>')
def admin_eliminar_facultad(id):
    if not session.get('admin_logged_in') or not session.get('p_config'): return redirect(url_for('admin'))
    f = Facultad.query.get_or_404(id)
    n = f.nombre
    db.session.delete(f)
    db.session.commit()
    registrar_log("CONFIG", f"Eliminó facultad: {n}")
    return redirect(url_for('admin_facultades'))

@app.route('/admin/escuelas', methods=['GET', 'POST'])
def admin_escuelas():
    if not session.get('admin_logged_in') or not session.get('p_config'): return redirect(url_for('admin'))
    if request.method == 'POST':
        n = request.form['nombre'].strip().upper()
        if not Escuela.query.filter_by(nombre=n).first():
            db.session.add(Escuela(nombre=n, facultad_id=request.form['facultad_id']))
            db.session.commit()
            registrar_log("CONFIG", f"Creó escuela: {n}")
    return render_template('admin_escuelas.html', escuelas=Escuela.query.order_by(Escuela.nombre).all(), facultades=Facultad.query.order_by(Facultad.nombre).all())

@app.route('/admin/escuelas/eliminar/<int:id>')
def admin_eliminar_escuela(id):
    if not session.get('admin_logged_in') or not session.get('p_config'): return redirect(url_for('admin'))
    e = Escuela.query.get_or_404(id)
    n = e.nombre
    db.session.delete(e)
    db.session.commit()
    registrar_log("CONFIG", f"Eliminó escuela: {n}")
    return redirect(url_for('admin_escuelas'))

@app.route('/admin/grados', methods=['GET', 'POST'])
def admin_grados():
    if not session.get('admin_logged_in') or not session.get('p_config'): return redirect(url_for('admin'))
    if request.method == 'POST':
        n = request.form['nombre'].strip().upper()
        if not Grado.query.filter_by(nombre=n).first():
            db.session.add(Grado(nombre=n))
            db.session.commit()
            registrar_log("CONFIG", f"Creó grado: {n}")
    return render_template('admin_grados.html', grados=Grado.query.order_by(Grado.nombre).all())

@app.route('/admin/grados/eliminar/<int:id>')
def admin_eliminar_grado(id):
    if not session.get('admin_logged_in') or not session.get('p_config'): return redirect(url_for('admin'))
    g = Grado.query.get_or_404(id)
    n = g.nombre
    db.session.delete(g)
    db.session.commit()
    registrar_log("CONFIG", f"Eliminó grado: {n}")
    return redirect(url_for('admin_grados'))

@app.route('/completar/<int:id>', methods=['GET', 'POST'])
def completar_datos(id):
    alumno = Alumno.query.get_or_404(id)
    if alumno.nombre and request.method == 'GET':
        flash("⚠️ Ya está registrado.")
        return render_template('atencion.html', alumno=alumno)
    if request.method == 'POST':
        paterno = request.form['paterno'].strip().upper()
        materno = request.form['materno'].strip().upper()
        nombres = request.form['nombres'].strip().upper()
        alumno.nombre = f"{paterno} {materno}, {nombres}"
        fac_obj = Facultad.query.get(int(request.form['facultad']))
        esc_obj = Escuela.query.get(int(request.form['escuela']))
        alumno.facultad = fac_obj.nombre
        alumno.escuela = esc_obj.nombre
        alumno.grado = request.form['grado'].strip().upper()
        year_actual = datetime.now().year
        ultimo = Alumno.query.filter(Alumno.anio_registro == year_actual).order_by(Alumno.numero_anual.desc()).first()
        alumno.numero_anual = (ultimo.numero_anual + 1) if (ultimo and ultimo.numero_anual) else 1
        alumno.anio_registro = year_actual
        db.session.commit()
        # Registrar log de que un alumno completó sus datos (opcional, pero útil)
        # registrar_log("SISTEMA", f"Alumno {alumno.nombre} generó constancia.") 
        flash("✅ ¡Registro Completado!")
        return render_template('atencion.html', alumno=alumno)
    return render_template('completar_datos.html', alumno=alumno, facultades=Facultad.query.order_by(Facultad.nombre).all(), grados=Grado.query.order_by(Grado.id).all())

@app.route('/descargar_pdf/<int:id>')
def descargar_pdf(id):
    alumno = Alumno.query.get_or_404(id)
    numero_final = alumno.numero_anual if alumno.numero_anual else alumno.id
    anio_final = alumno.anio_registro if alumno.anio_registro else datetime.now().year
    correlativo = f"{str(numero_final).zfill(3)}-{anio_final}-UB/DBU-UNAP"
    txt_facultad = alumno.facultad.replace("FACULTAD DE ", "").replace("FACULTAD ", "")
    fecha_texto = f"{datetime.now().day} de {('enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre')[datetime.now().month-1]} de {datetime.now().year}"
    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=A4)
    c.setFont("Times-Bold", 14) 
    c.drawString(180, 700, f"CONSTANCIA N° {correlativo}")
    c.line(180, 697, 180 + c.stringWidth(f"CONSTANCIA N° {correlativo}", "Times-Bold", 14), 697)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(180, 656, f"{alumno.nombre}")
    c.drawString(180, 615, f"{txt_facultad}")
    c.drawString(180, 575, f"{alumno.escuela}")
    c.setFont("Helvetica", 12)
    c.drawString(280, 430, f"San Juan Bautista, {fecha_texto}.")
    c.save()
    packet.seek(0)
    try:
        new_pdf = PdfReader(packet)
        existing_pdf = PdfReader(open("fondo_constancia.pdf", "rb"))
        output = PdfWriter()
        page = existing_pdf.pages[0]
        page.merge_page(new_pdf.pages[0])
        output.add_page(page)
        output.encrypt(user_password="", owner_password="Sistema_Biblioteca_Seguro_2025", permissions_flag=UserAccessPermissions.PRINT)
        pdf_final = io.BytesIO()
        output.write(pdf_final)
        pdf_final.seek(0)
        return send_file(pdf_final, as_attachment=True, download_name=f"Constancia_{alumno.voucher}.pdf", mimetype='application/pdf')
    except Exception as e: return f"Error generando PDF: {str(e)}"

# --- INIT ---
with app.app_context():
    db.create_all()
    if not Administrador.query.filter_by(usuario='admin').first():
        db.session.add(Administrador(usuario='admin', password=generate_password_hash('admin123'), p_pagos=True, p_deudores=True, p_reportes=True, p_config=True, p_usuarios=True))
        db.session.commit()
    if Facultad.query.count() == 0:
        facs = ["FACULTAD DE CIENCIAS ECONÓMICAS Y DE NEGOCIOS", "FACULTAD DE INGENIERÍA DE SISTEMAS E INFORMÁTICA", "FACULTAD DE DERECHO Y CIENCIAS POLÍTICAS"]
        for f in facs: db.session.add(Facultad(nombre=f))
        db.session.commit()
    if Escuela.query.count() == 0:
        f_econ = Facultad.query.filter_by(nombre="FACULTAD DE CIENCIAS ECONÓMICAS Y DE NEGOCIOS").first()
        f_sist = Facultad.query.filter_by(nombre="FACULTAD DE INGENIERÍA DE SISTEMAS E INFORMÁTICA").first()
        f_der = Facultad.query.filter_by(nombre="FACULTAD DE DERECHO Y CIENCIAS POLÍTICAS").first()
        data = {f_econ: ["CONTABILIDAD", "ADMINISTRACIÓN", "ECONOMÍA"], f_sist: ["INGENIERÍA DE SISTEMAS"], f_der: ["DERECHO"]}
        for fac, escuelas in data.items():
            if fac: 
                for e in escuelas: db.session.add(Escuela(nombre=e, facultad_id=fac.id))
        db.session.commit()
    if Grado.query.count() == 0:
        for g in ["BACHILLER", "TÍTULO PROFESIONAL", "MAESTRÍA", "DOCTORADO"]: db.session.add(Grado(nombre=g))
        db.session.commit()
        print("✅ BD OK.")

if __name__ == '__main__':
    app.run(debug=True)