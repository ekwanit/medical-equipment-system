# เพิ่มที่ต้นไฟล์
import os
import sys

import streamlit as st
import pandas as pd
import qrcode
import cv2
from PIL import Image
import json
import sqlite3
from datetime import datetime
import numpy as np
from io import BytesIO
import base64
import warnings

# ปิด FutureWarning ของ pandas
warnings.filterwarnings('ignore', category=FutureWarning)
pd.set_option('future.no_silent_downcasting', True)

# สร้างโฟลเดอร์สำหรับฐานข้อมูลถ้ายังไม่มี
if not os.path.exists('data'):
    os.makedirs('data')

# ใช้ path ของฐานข้อมูลที่ชัดเจน
DB_PATH = 'data/medical_equipment.db'

# ตั้งค่าหน้าเว็บ
st.set_page_config(
    page_title="ระบบเบิกเครื่องมือแพทย์",
    page_icon="🏥",
    layout="wide"
)

# ฟังก์ชันตรวจสอบคอลัมน์
def column_exists(cursor, table_name, column_name):
    try:
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in cursor.fetchall()]
        return column_name in columns
    except sqlite3.OperationalError:
        return False

# ฟังก์ชันสร้างฐานข้อมูล
def init_database():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    cursor = conn.cursor()
    
    try:
        # สร้างตาราง equipment
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS equipment (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # สร้างตาราง transactions (ปรับปรุงเพื่อรองรับการคืนบางส่วน)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT PRIMARY KEY,
                equipment_id TEXT NOT NULL,
                equipment_name TEXT NOT NULL,
                borrower_name TEXT NOT NULL,
                borrower_dept TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                returned_quantity INTEGER DEFAULT 0,
                remaining_quantity INTEGER NOT NULL,
                unit TEXT NOT NULL,
                date TEXT NOT NULL,
                status TEXT NOT NULL,
                notes TEXT,
                fully_returned BOOLEAN DEFAULT FALSE,
                last_return_date TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (equipment_id) REFERENCES equipment (id)
            )
        ''')
        
        # สร้างตาราง return_history (เก็บประวัติการคืนแต่ละครั้ง)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS return_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id TEXT NOT NULL,
                returned_quantity INTEGER NOT NULL,
                return_date TEXT NOT NULL,
                notes TEXT,
                FOREIGN KEY (transaction_id) REFERENCES transactions (id)
            )
        ''')
        
        # เพิ่มคอลัมน์ใหม่ถ้ายังไม่มี (ทีละคอลัมน์เพื่อป้องกัน error)
        columns_to_add = [
            ("returned_quantity", "INTEGER DEFAULT 0"),
            ("remaining_quantity", "INTEGER"),
            ("fully_returned", "BOOLEAN DEFAULT FALSE"),
            ("last_return_date", "TEXT")
        ]
        
        for column_name, column_def in columns_to_add:
            if not column_exists(cursor, "transactions", column_name):
                try:
                    cursor.execute(f"ALTER TABLE transactions ADD COLUMN {column_name} {column_def}")
                    print(f"เพิ่มคอลัมน์ {column_name} สำเร็จ")
                except sqlite3.OperationalError as e:
                    print(f"ไม่สามารถเพิ่มคอลัมน์ {column_name}: {e}")
        
        # อัพเดทข้อมูลเก่าให้มีค่าที่ถูกต้อง (เฉพาะกรณีที่มีคอลัมน์ returned เก่า)
        if column_exists(cursor, "transactions", "returned"):
            try:
                cursor.execute('''
                    UPDATE transactions 
                    SET returned_quantity = CASE WHEN returned = 1 THEN quantity ELSE 0 END,
                        remaining_quantity = CASE WHEN returned = 1 THEN 0 ELSE quantity END,
                        fully_returned = returned
                    WHERE returned_quantity IS NULL OR remaining_quantity IS NULL
                ''')
                print("อัพเดทข้อมูลเก่าจาก returned column สำเร็จ")
            except sqlite3.OperationalError as e:
                print(f"ไม่สามารถอัพเดทข้อมูลเก่า: {e}")
        else:
            # อัพเดทข้อมูลที่ remaining_quantity เป็น NULL
            try:
                cursor.execute('''
                    UPDATE transactions 
                    SET remaining_quantity = quantity,
                        returned_quantity = 0,
                        fully_returned = FALSE
                    WHERE remaining_quantity IS NULL
                ''')
                print("อัพเดทข้อมูลที่ขาดค่า remaining_quantity สำเร็จ")
            except sqlite3.OperationalError as e:
                print(f"ไม่สามารถอัพเดทข้อมูล remaining_quantity: {e}")
        
        # ใส่ข้อมูลเริ่มต้น (ถ้ายังไม่มี)
        cursor.execute("SELECT COUNT(*) FROM equipment")
        if cursor.fetchone()[0] == 0:
            initial_equipment = [
                ("EQ001", "เครื่องวัดความดัน", "การตรวจ", 10, "เครื่อง"),
                ("EQ002", "หูฟังแพทย์", "การตรวจ", 5, "อัน"),
                ("EQ003", "เทอร์โมมิเตอร์", "การตรวจ", 15, "อัน"),
                ("EQ004", "ถุงมือยาง", "อุปกรณ์ความปลอดภัย", 100, "คู่"),
                ("EQ005", "แอลกอฮอล์เจล", "อุปกรณ์ความปลอดภัย", 50, "ขวด")
            ]
            
            cursor.executemany('''
                INSERT INTO equipment (id, name, category, quantity, unit)
                VALUES (?, ?, ?, ?, ?)
            ''', initial_equipment)
            print("เพิ่มข้อมูลเครื่องมือเริ่มต้นสำเร็จ")
        
        conn.commit()
        print("เริ่มต้นฐานข้อมูลสำเร็จ")
        
    except Exception as e:
        print(f"เกิดข้อผิดพลาดในการเริ่มต้นฐานข้อมูล: {e}")
        conn.rollback()
        raise e
    finally:
        conn.close()

# ฟังก์ชันโหลดข้อมูลเครื่องมือ
@st.cache_data
def load_equipment():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    try:
        df = pd.read_sql_query("SELECT * FROM equipment ORDER BY id", conn)
        return df
    finally:
        conn.close()

# ฟังก์ชันโหลดข้อมูลการเบิก
@st.cache_data
def load_transactions():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    try:
        df = pd.read_sql_query('''
            SELECT * FROM transactions 
            ORDER BY created_at DESC
        ''', conn)
        return df
    finally:
        conn.close()

# ฟังก์ชันโหลดประวัติการคืน
@st.cache_data
def load_return_history(transaction_id):
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    try:
        df = pd.read_sql_query('''
            SELECT * FROM return_history 
            WHERE transaction_id = ?
            ORDER BY return_date DESC
        ''', conn, params=(transaction_id,))
        return df
    finally:
        conn.close()

# ฟังก์ชันเพิ่มเครื่องมือใหม่
def add_equipment(eq_id, name, category, quantity, unit):
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO equipment (id, name, category, quantity, unit)
            VALUES (?, ?, ?, ?, ?)
        ''', (eq_id, name, category, quantity, unit))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    except Exception as e:
        print(f"Error adding equipment: {e}")
        return False
    finally:
        conn.close()

# ฟังก์ชันอัพเดทจำนวนเครื่องมือ
def update_equipment_quantity(eq_id, new_quantity):
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE equipment 
            SET quantity = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (new_quantity, eq_id))
        conn.commit()
    finally:
        conn.close()

# ฟังก์ชันเบิกเครื่องมือ
def withdraw_equipment(transaction_id, equipment_id, equipment_name, borrower_name, 
                      borrower_dept, quantity, unit, notes):
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    cursor = conn.cursor()
    
    try:
        # เพิ่มรายการเบิก
        cursor.execute('''
            INSERT INTO transactions 
            (id, equipment_id, equipment_name, borrower_name, borrower_dept, 
             quantity, returned_quantity, remaining_quantity, unit, date, status, notes, fully_returned)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (transaction_id, equipment_id, equipment_name, borrower_name, 
              borrower_dept, quantity, 0, quantity, unit, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              "เบิกแล้ว", notes, False))
        
        # ลดจำนวนเครื่องมือ
        cursor.execute('''
            UPDATE equipment 
            SET quantity = quantity - ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (quantity, equipment_id))
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        st.error(f"เกิดข้อผิดพลาด: {str(e)}")
        return False
    finally:
        conn.close()

# ฟังก์ชันคืนเครื่องมือบางส่วน
def partial_return_equipment(transaction_id, return_quantity, notes=""):
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    cursor = conn.cursor()
    
    try:
        # ดึงข้อมูลการเบิก
        cursor.execute('''
            SELECT equipment_id, remaining_quantity, quantity FROM transactions 
            WHERE id = ? AND fully_returned = FALSE
        ''', (transaction_id,))
        
        result = cursor.fetchone()
        if not result:
            return False, "ไม่พบรายการเบิกหรือคืนครบแล้ว"
        
        equipment_id, current_remaining, total_quantity = result
        
        # ตรวจสอบจำนวนที่คืน
        if return_quantity > current_remaining:
            return False, f"จำนวนที่คืนเกินกว่าที่เหลือ (เหลือ {current_remaining} ชิ้น)"
        
        if return_quantity <= 0:
            return False, "จำนวนที่คืนต้องมากกว่า 0"
        
        # คำนวณจำนวนใหม่
        new_returned_quantity = total_quantity - current_remaining + return_quantity
        new_remaining_quantity = current_remaining - return_quantity
        is_fully_returned = new_remaining_quantity == 0
        
        # อัพเดทข้อมูลการเบิก
        cursor.execute('''
            UPDATE transactions 
            SET returned_quantity = ?,
                remaining_quantity = ?,
                fully_returned = ?,
                last_return_date = ?,
                status = ?
            WHERE id = ?
        ''', (new_returned_quantity, new_remaining_quantity, is_fully_returned,
              datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              "คืนครบแล้ว" if is_fully_returned else "คืนบางส่วน",
              transaction_id))
        
        # บันทึกประวัติการคืน
        cursor.execute('''
            INSERT INTO return_history (transaction_id, returned_quantity, return_date, notes)
            VALUES (?, ?, ?, ?)
        ''', (transaction_id, return_quantity, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), notes))
        
        # เพิ่มจำนวนเครื่องมือกลับ
        cursor.execute('''
            UPDATE equipment 
            SET quantity = quantity + ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (return_quantity, equipment_id))
        
        conn.commit()
        return True, f"คืนสำเร็จ {return_quantity} ชิ้น (เหลือ {new_remaining_quantity} ชิ้น)"
        
    except Exception as e:
        conn.rollback()
        return False, f"เกิดข้อผิดพลาด: {str(e)}"
    finally:
        conn.close()

# ฟังก์ชันลบรายการเบิกทั้งหมด
def clear_all_transactions():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM transactions")
        cursor.execute("DELETE FROM return_history")
        conn.commit()
    finally:
        conn.close()

# ฟังก์ชันดึงข้อมูลการเบิกเฉพาะ
def get_transaction(transaction_id):
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT * FROM transactions 
            WHERE id = ? AND fully_returned = FALSE
        ''', (transaction_id,))
        
        result = cursor.fetchone()
        
        if result:
            columns = [description[0] for description in cursor.description]
            return dict(zip(columns, result))
        
        # ถ้าไม่พบหรือคืนครบแล้ว ให้ดูข้อมูลทั้งหมด
        cursor.execute('''
            SELECT * FROM transactions 
            WHERE id = ?
        ''', (transaction_id,))
        
        result = cursor.fetchone()
        
        if result:
            columns = [description[0] for description in cursor.description]
            return dict(zip(columns, result))
        return None
    finally:
        conn.close()

# ฟังก์ชันสร้าง QR Code
def generate_qr_code(data):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    return img

# ฟังก์ชันอ่าน QR Code จากรูปภาพ
def read_qr_code(image):
    try:
        # แปลง PIL Image เป็น numpy array
        img_array = np.array(image)
        
        # แปลงเป็น grayscale ถ้าเป็นรูปสี
        if len(img_array.shape) == 3:
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        else:
            gray = img_array
        
        # ปรับปรุงคุณภาพภาพ
        gray = cv2.convertScaleAbs(gray, alpha=1.5, beta=0)
        gray = cv2.medianBlur(gray, 5)
        
        # ใช้ cv2 อ่าน QR Code
        detector = cv2.QRCodeDetector()
        data, vertices_array, binary_qrcode = detector.detectAndDecode(gray)
        
        if vertices_array is not None and data:
            return data
        
        # ลองวิธีอื่นถ้าไม่ได้
        _, thresh = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
        data, vertices_array, binary_qrcode = detector.detectAndDecode(thresh)
        
        if vertices_array is not None and data:
            return data
        
        # ลองกลับสี
        thresh_inv = cv2.bitwise_not(thresh)
        data, vertices_array, binary_qrcode = detector.detectAndDecode(thresh_inv)
        
        if vertices_array is not None and data:
            return data
            
        return None
        
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการอ่าน QR Code: {str(e)}")
        return None

# ฟังก์ชันประมวลผลการคืนเครื่องมือ
def process_qr_return(qr_data):
    try:
        # แปลงข้อมูล JSON
        transaction_data = json.loads(qr_data)
        transaction_id = transaction_data.get("transaction_id")
        
        # ดึงข้อมูลการเบิก
        transaction = get_transaction(transaction_id)
        
        if transaction:
            # ตรวจสอบสถานะ
            if transaction['fully_returned']:
                st.warning("⚠️ รายการนี้คืนครบแล้ว")
                
                # แสดงรายละเอียด
                st.subheader("รายละเอียดการเบิก (คืนครบแล้ว)")
                col1, col2 = st.columns(2)
                
                with col1:
                    st.write(f"**รหัสการเบิก:** {transaction['id']}")
                    st.write(f"**เครื่องมือ:** {transaction['equipment_name']}")
                    st.write(f"**ผู้เบิก:** {transaction['borrower_name']}")
                    st.write(f"**แผนก:** {transaction['borrower_dept']}")
                
                with col2:
                    st.write(f"**จำนวนที่เบิก:** {transaction['quantity']} {transaction['unit']}")
                    st.write(f"**จำนวนที่คืนแล้ว:** {transaction['returned_quantity']} {transaction['unit']}")
                    st.write(f"**วันที่เบิก:** {transaction['date']}")
                    if transaction.get('last_return_date'):
                        st.write(f"**วันที่คืนล่าสุด:** {transaction['last_return_date']}")
                
                return
            
            # รายการยังไม่คืนครบ
            st.success("✅ พบรายการเบิกที่ยังไม่คืนครบ!")
            
            # แสดงรายละเอียด
            st.subheader("รายละเอียดการเบิก")
            col1, col2 = st.columns(2)
            
            with col1:
                st.write(f"**รหัสการเบิก:** {transaction['id']}")
                st.write(f"**เครื่องมือ:** {transaction['equipment_name']}")
                st.write(f"**ผู้เบิก:** {transaction['borrower_name']}")
                st.write(f"**แผนก:** {transaction['borrower_dept']}")
            
            with col2:
                st.write(f"**จำนวนที่เบิก:** {transaction['quantity']} {transaction['unit']}")
                st.write(f"**จำนวนที่คืนแล้ว:** {transaction['returned_quantity']} {transaction['unit']}")
                st.write(f"**จำนวนที่เหลือ:** {transaction['remaining_quantity']} {transaction['unit']}")
                st.write(f"**วันที่เบิก:** {transaction['date']}")
                if transaction.get('notes'):
                    st.write(f"**หมายเหตุ:** {transaction['notes']}")
            
            # ฟอร์มการคืน
            st.subheader("🔄 คืนเครื่องมือ")
            
            with st.form("return_form"):
                col1, col2 = st.columns(2)
                
                with col1:
                    return_quantity = st.number_input(
                        f"จำนวนที่ต้องการคืน (เหลือ {transaction['remaining_quantity']} {transaction['unit']})",
                        min_value=1,
                        max_value=transaction['remaining_quantity'],
                        value=min(1, transaction['remaining_quantity'])
                    )
                
                with col2:
                    return_notes = st.text_input("หมายเหตุการคืน", placeholder="หมายเหตุเพิ่มเติม (ถ้ามี)")
                
                # ปุ่มคืน
                col_btn1, col_btn2 = st.columns(2)
                
                with col_btn1:
                    partial_return_submitted = st.form_submit_button("🔄 คืนตามจำนวนที่ระบุ", type="primary")
                
                with col_btn2:
                    full_return_submitted = st.form_submit_button("🔄 คืนทั้งหมด", type="secondary")
                
                if partial_return_submitted or full_return_submitted:
                    # กำหนดจำนวนที่คืน
                    qty_to_return = transaction['remaining_quantity'] if full_return_submitted else return_quantity
                    
                    # ประมวลผลการคืน
                    success, message = partial_return_equipment(transaction_id, qty_to_return, return_notes)
                    
                    if success:
                        st.success(f"✅ {message}")
                        st.balloons()
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(f"❌ {message}")
        
        else:
            st.error("❌ ไม่พบรายการเบิกที่ตรงกัน")
    
    except json.JSONDecodeError:
        st.error("❌ รูปแบบ QR Code ไม่ถูกต้อง")
    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาด: {str(e)}")

# เริ่มต้นฐานข้อมูล
try:
    init_database()
except Exception as e:
    st.error(f"❌ เกิดข้อผิดพลาดในการเริ่มต้นฐานข้อมูล: {str(e)}")

# หัวข้อหลัก
st.title("🏥 ระบบเบิกเครื่องมือแพทย์")

# ปุ่ม Refresh
col1, col2, col3 = st.columns([1, 1, 8])
with col1:
    if st.button("🔄 รีเฟรช", help="รีเฟรชข้อมูลทั้งหมด"):
        st.cache_data.clear()
        st.rerun()

with col2:
    st.caption(f"🕐 อัพเดท: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

st.markdown("---")

# สร้าง Sidebar สำหรับเมนู
st.sidebar.title("เมนูหลัก")
menu = st.sidebar.selectbox(
    "เลือกหน้าที่ต้องการ",
    ["📋 รายการเครื่องมือ", "📤 เบิกเครื่องมือ", "📱 สแกน QR Code", "📊 รายงาน", "⚙️ จัดการระบบ"]
)

# หน้ารายการเครื่องมือ
if menu == "📋 รายการเครื่องมือ":
    st.header("📋 รายการเครื่องมือทั้งหมด")
    
    # โหลดข้อมูลเครื่องมือและการเบิก
    df_equipment = load_equipment()
    df_transactions = load_transactions()
    
    if not df_equipment.empty:
        # คำนวณจำนวนที่ยังไม่คืนของแต่ละเครื่องมือ
        not_returned = df_transactions[df_transactions['fully_returned'] == False].groupby('equipment_id')['remaining_quantity'].sum().reset_index()
        not_returned.columns = ['id', 'borrowed_quantity']
        
        # รวมข้อมูลเครื่องมือกับจำนวนที่เบิกไปแล้ว
        df_display = df_equipment.merge(not_returned, on='id', how='left')
        df_display['borrowed_quantity'] = df_display['borrowed_quantity'].fillna(0)
        df_display['borrowed_quantity'] = df_display['borrowed_quantity'].astype(int)
        df_display['total_quantity'] = df_display['quantity'] + df_display['borrowed_quantity']
        
        # จัดเรียงคอลัมน์สำหรับแสดงผล
        display_cols = df_display[['id', 'name', 'category', 'total_quantity', 'quantity', 'borrowed_quantity', 'unit']].copy()
        display_cols.columns = ["รหัส", "ชื่อเครื่องมือ", "หมวดหมู่", "จำนวนรวม", "คงเหลือ", "เบิกไปแล้ว", "หน่วย"]
        
        st.dataframe(display_cols, use_container_width=True)
        
        # คำอธิบาย
        st.info("💡 **คำอธิบาย:** จำนวนรวม = คงเหลือ + เบิกไปแล้ว (ยังไม่คืน)")
        
        # สถิติรวม
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("จำนวนประเภทเครื่องมือ", len(df_equipment))
        with col2:
            total_items = df_display['total_quantity'].sum()
            st.metric("จำนวนรวมทั้งหมด", total_items)
        with col3:
            available_items = df_display['quantity'].sum()
            st.metric("จำนวนคงเหลือ", available_items)
        with col4:
            borrowed_items = df_display['borrowed_quantity'].sum()
            st.metric("จำนวนเบิกไปแล้ว", borrowed_items)
    else:
        st.info("ไม่มีข้อมูลเครื่องมือ")

# หน้าเบิกเครื่องมือ
elif menu == "📤 เบิกเครื่องมือ":
    st.header("📤 เบิกเครื่องมือ")
    
    # ใช้ session state เพื่อเก็บข้อมูลการเบิก
    if 'withdrawal_success' not in st.session_state:
        st.session_state.withdrawal_success = False
        st.session_state.transaction_data = None

    with st.form("withdrawal_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            # ข้อมูลผู้เบิก
            borrower_name = st.text_input("ชื่อผู้เบิก", placeholder="กรุณาใส่ชื่อผู้เบิก")
            borrower_dept = st.text_input("แผนก", placeholder="แผนกที่สังกัด")
            
        with col2:
            # โหลดข้อมูลเครื่องมือที่มีสต็อก
            df_equipment = load_equipment()
            available_equipment = df_equipment[df_equipment['quantity'] > 0]
            
            if not available_equipment.empty:
                equipment_options = [
                    f"{row['id']} - {row['name']} (คงเหลือ: {row['quantity']} {row['unit']})" 
                    for _, row in available_equipment.iterrows()
                ]
                
                selected_equipment = st.selectbox("เลือกเครื่องมือ", equipment_options)
                quantity = st.number_input("จำนวนที่ต้องการเบิก", min_value=1, value=1)
            else:
                st.warning("ไม่มีเครื่องมือที่สามารถเบิกได้")
                equipment_options = []
        
        # หมายเหตุ
        notes = st.text_area("หมายเหตุ", placeholder="หมายเหตุเพิ่มเติม (ถ้ามี)")
        
        # ปุ่มยืนยันการเบิก
        submitted = st.form_submit_button("ยืนยันการเบิก", type="primary")
        
        if submitted and equipment_options:
            if borrower_name and borrower_dept:
                # ดึงข้อมูลเครื่องมือที่เลือก
                equipment_id = selected_equipment.split(" - ")[0]
                equipment_row = df_equipment[df_equipment['id'] == equipment_id].iloc[0]
                
                if equipment_row['quantity'] >= quantity:
                    # สร้างรายการเบิก
                    transaction_id = f"TX{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    
                    # บันทึกการเบิก
                    success = withdraw_equipment(
                        transaction_id, equipment_id, equipment_row['name'],
                        borrower_name, borrower_dept, quantity, equipment_row['unit'], notes
                    )
                    
                    if success:
                        # สร้าง QR Code สำหรับรายการเบิก
                        qr_data = json.dumps({
                            "transaction_id": transaction_id,
                            "equipment_id": equipment_id,
                            "quantity": quantity,
                            "borrower": borrower_name
                        })
                        qr_img = generate_qr_code(qr_data)
                        
                        # เก็บข้อมูลใน session state
                        st.session_state.withdrawal_success = True
                        st.session_state.transaction_data = {
                            "id": transaction_id,
                            "equipment_name": equipment_row['name'],
                            "borrower_name": borrower_name,
                            "borrower_dept": borrower_dept,
                            "quantity": quantity,
                            "unit": equipment_row['unit'],
                            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "notes": notes
                        }
                        st.session_state.qr_img = qr_img
                        
                        # Clear cache
                        st.cache_data.clear()
                        st.success("✅ เบิกเครื่องมือสำเร็จ!")
                        st.rerun()
                    
                else:
                    st.error("❌ จำนวนเครื่องมือไม่เพียงพอ!")
            else:
                st.error("❌ กรุณากรอกข้อมูลให้ครบถ้วน!")

    # แสดงผลลัพธ์หลังจากเบิกสำเร็จ (นอก form)
    if st.session_state.withdrawal_success and st.session_state.transaction_data:
        transaction = st.session_state.transaction_data
        qr_img = st.session_state.qr_img
        
        st.subheader("รายละเอียดการเบิก")
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.write(f"**รหัสการเบิก:** {transaction['id']}")
            st.write(f"**เครื่องมือ:** {transaction['equipment_name']}")
            st.write(f"**ผู้เบิก:** {transaction['borrower_name']}")
            st.write(f"**แผนก:** {transaction['borrower_dept']}")
            st.write(f"**จำนวน:** {transaction['quantity']} {transaction['unit']}")
            st.write(f"**วันที่:** {transaction['date']}")
            if transaction['notes']:
                st.write(f"**หมายเหตุ:** {transaction['notes']}")
        
        with col2:
            st.write("**QR Code สำหรับการคืน:**")
            
            # แปลง PIL Image เป็น bytes สำหรับ Streamlit
            buf = BytesIO()
            qr_img.save(buf, format='PNG')
            buf.seek(0)
            
            # แสดง QR Code
            st.image(buf.getvalue(), width=200)
        
        # ปุ่มดาวน์โหลด (นอก form)
        buf.seek(0)
        st.download_button(
            label="💾 ดาวน์โหลด QR Code",
            data=buf.getvalue(),
            file_name=f"QR_{transaction['id']}.png",
            mime="image/png",
            key="download_qr"
        )
        
        # ปุ่มเคลียร์เพื่อเบิกใหม่
        if st.button("🔄 เบิกเครื่องมือใหม่", key="new_withdrawal"):
            st.session_state.withdrawal_success = False
            st.session_state.transaction_data = None
            st.session_state.qr_img = None
            st.rerun()

        # คำแนะนำการใช้งาน QR Code
        st.info("💡 **คำแนะนำ:** QR Code นี้สามารถใช้คืนเครื่องมือแบบบางส่วนได้ เช่น คืน 2 ชิ้นจาก 10 ชิ้น แล้วใช้ QR Code เดิมคืนอีก 3 ชิ้น จนกว่าจะคืนครบ")

# หน้าสแกน QR Code
elif menu == "📱 สแกน QR Code":
    st.header("📱 สแกน QR Code เพื่อคืนเครื่องมือ")
    
    # เลือกวิธีการป้อนข้อมูล
    input_method = st.radio(
        "เลือกวิธีการป้อนข้อมูล QR Code:",
        ["อัพโหลดรูป QR Code", "ป้อนข้อมูลจากการสแกนด้วยมือถือ"]
    )
    
    if input_method == "อัพโหลดรูป QR Code":
        # อัพโหลดไฟล์รูปภาพ
        uploaded_file = st.file_uploader(
            "อัพโหลดรูป QR Code", 
            type=['png', 'jpg', 'jpeg'],
            help="อัพโหลดรูป QR Code ที่ได้รับตอนเบิกเครื่องมือ"
        )
        
        if uploaded_file is not None:
            # แสดงรูปที่อัพโหลด
            image = Image.open(uploaded_file)
            col1, col2 = st.columns([1, 2])
            
            with col1:
                st.image(image, caption="รูป QR Code ที่อัพโหลด", width=300)
            
            with col2:
                # อ่าน QR Code
                qr_data = read_qr_code(image)
                
                if qr_data:
                    process_qr_return(qr_data)
                else:
                    st.error("❌ ไม่สามารถอ่าน QR Code ได้ กรุณาตรวจสอบรูปภาพ")
    
    else:  # ป้อนข้อมูลจากการสแกนด้วยมือถือ
        st.info("💡 **วิธีใช้:** สแกน QR Code ด้วยมือถือ แล้ว Copy ข้อมูลมาวางในช่องด้านล่าง")
        
        # แสดงคำแนะนำการสแกนด้วยมือถือ
        with st.expander("📋 คำแนะนำการสแกน QR Code ด้วยมือถือ"):
            st.markdown("""
            **iPhone:**
            - เปิดแอพ Camera → ส่องไปที่ QR Code → แตะ notification ที่ปรากฏ
            - หรือปัดลง Control Center → แตะไอคอน QR Code
            
            **Android:**
            - ใช้ Google Lens: เปิดแอพ Google → แตะไอคอน Lens → ส่องไปที่ QR Code
            - หรือเปิดแอพ Camera → เลือกโหมด QR Code/Barcode
            
            **แอพแนะนำ:**
            - QR Code Reader (ฟรี)
            - Google Lens
            - LINE (มีฟีเจอร์สแกน QR Code)
            """)
        
        # ช่องป้อนข้อมูล QR Code
        qr_text_input = st.text_area(
            "ข้อมูล QR Code ที่สแกนได้:",
            placeholder="วางข้อมูลที่ได้จากการสแกน QR Code ด้วยมือถือที่นี่...",
            height=100
        )
        
        # ปุ่มประมวลผล
        if st.button("🔍 ตรวจสอบข้อมูลการคืน", type="primary"):
            if qr_text_input.strip():
                process_qr_return(qr_text_input.strip())
            else:
                st.error("❌ กรุณาป้อนข้อมูล QR Code")
        
        # ปุ่มทดสอบระบบ
        st.markdown("---")
        st.subheader("🧪 ทดสอบระบบ")
        if st.button("🔧 ทดสอบด้วยข้อมูลจำลอง"):
            test_data = '{"transaction_id": "TX20250611162200", "equipment_id": "EQ005", "quantity": 10, "borrower": "ทดสอบ"}'
            st.text_area("ข้อมูลทดสอบ (Copy ไปใส่ในช่องข้างบน):", test_data, height=100)
            st.info("💡 **คำแนะนำ:** Copy ข้อมูลข้างบนไปใส่ในช่องด้านบน แล้วกดปุ่ม 'ตรวจสอบข้อมูลการคืน' เพื่อทดสอบการคืนแบบบางส่วน")

# หน้ารายงาน
elif menu == "📊 รายงาน":
    st.header("📊 รายงานการเบิก-คืนเครื่องมือ")
    
    # โหลดข้อมูลการเบิก
    df_transactions = load_transactions()
    
    if not df_transactions.empty:
        # สถิติรวม
        col1, col2, col3, col4 = st.columns(4)
        
        total_transactions = len(df_transactions)
        fully_returned_count = len(df_transactions[df_transactions['fully_returned'] == True])
        partial_returned_count = len(df_transactions[(df_transactions['returned_quantity'] > 0) & (df_transactions['fully_returned'] == False)])
        not_returned_count = len(df_transactions[df_transactions['returned_quantity'] == 0])
        
        with col1:
            st.metric("รายการเบิกทั้งหมด", total_transactions)
        with col2:
            st.metric("คืนครบแล้ว", fully_returned_count)
        with col3:
            st.metric("คืนบางส่วน", partial_returned_count)
        with col4:
            st.metric("ยังไม่คืน", not_returned_count)
        
        # ตารางรายการเบิก-คืน
        st.subheader("รายการเบิก-คืนล่าสุด")
        
        display_columns = [
            "id", "equipment_name", "borrower_name", "borrower_dept", 
            "quantity", "returned_quantity", "remaining_quantity", "unit", "date", "status", "notes"
        ]
        
        df_display = df_transactions[display_columns].copy()
        df_display.columns = [
            "รหัสการเบิก", "ชื่อเครื่องมือ", "ผู้เบิก", "แผนก", 
            "จำนวนเบิก", "จำนวนคืนแล้ว", "จำนวนเหลือ", "หน่วย", "วันที่เบิก", "สถานะ", "หมายเหตุ"
        ]
        
        # กรองข้อมูลตามสถานะ
        status_filter = st.selectbox("กรองตามสถานะ", ["ทั้งหมด", "เบิกแล้ว", "คืนบางส่วน", "คืนครบแล้ว"])
        
        if status_filter != "ทั้งหมด":
            df_display = df_display[df_display["สถานะ"] == status_filter]
        
        st.dataframe(df_display, use_container_width=True)
        
        # กราฟแสดงสถิติ
        st.subheader("📈 สถิติการใช้งาน")
        
        col1, col2 = st.columns(2)
        
        with col1:
            # กราฟวงกลมแสดงสถานะ
            status_counts = df_transactions['status'].value_counts()
            if not status_counts.empty:
                import plotly.express as px
                fig_pie = px.pie(
                    values=status_counts.values, 
                    names=status_counts.index,
                    title="สัดส่วนสถานะการเบิก-คืน"
                )
                st.plotly_chart(fig_pie, use_container_width=True)
        
        with col2:
            # กราฟแท่งแสดงเครื่องมือที่เบิกมากที่สุด
            equipment_counts = df_transactions['equipment_name'].value_counts().head(10)
            if not equipment_counts.empty:
                fig_bar = px.bar(
                    x=equipment_counts.values,
                    y=equipment_counts.index,
                    orientation='h',
                    title="เครื่องมือที่เบิกมากที่สุด (Top 10)",
                    labels={'x': 'จำนวนครั้ง', 'y': 'เครื่องมือ'}
                )
                fig_bar.update_layout(yaxis={'categoryorder': 'total ascending'})
                st.plotly_chart(fig_bar, use_container_width=True)
        
        # แสดงสถิติการคืนบางส่วน
        st.subheader("📊 สถิติการคืนบางส่วน")
        
        partial_returns = df_transactions[df_transactions['returned_quantity'] > 0]
        if not partial_returns.empty:
            col1, col2, col3 = st.columns(3)
            
            with col1:
                total_borrowed = partial_returns['quantity'].sum()
                st.metric("จำนวนเบิกรวม", total_borrowed)
            
            with col2:
                total_returned = partial_returns['returned_quantity'].sum()
                st.metric("จำนวนคืนแล้ว", total_returned)
            
            with col3:
                total_remaining = partial_returns['remaining_quantity'].sum()
                st.metric("จำนวนที่เหลือ", total_remaining)
        
        # เตรียมข้อมูลสำหรับ export
        df_export = df_transactions[display_columns].copy()
        
        # แปลงข้อมูลสถานะให้อ่านง่าย
        df_export['status_eng'] = df_export['status'].map({
            'เบิกแล้ว': 'Not Returned',
            'คืนบางส่วน': 'Partial Return', 
            'คืนครบแล้ว': 'Fully Returned'
        })
        
        # แปลงวันที่ให้อ่านง่าย
        df_export['date_formatted'] = pd.to_datetime(df_export['date']).dt.strftime('%d/%m/%Y %H:%M')
        
        # จัดเรียงคอลัมน์ใหม่
        df_export = df_export[['id', 'equipment_name', 'borrower_name', 'borrower_dept', 
                              'quantity', 'returned_quantity', 'remaining_quantity', 
                              'unit', 'date_formatted', 'status_eng', 'notes']].copy()
        
        df_export.columns = [
            "Transaction_ID", "Equipment_Name", "Borrower_Name", "Department", 
            "Total_Quantity", "Returned_Quantity", "Remaining_Quantity", 
            "Unit", "Borrow_Date", "Status", "Notes"
        ]
        
        # สร้างไฟล์ Excel
        output = BytesIO()
        
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Sheet ข้อมูลหลัก
            df_export.to_excel(writer, sheet_name='รายการเบิก-คืน', index=False)
            
            # Sheet สรุป
            summary_data = {
                'รายการ': ['รายการเบิกทั้งหมด', 'คืนครบแล้ว', 'คืนบางส่วน', 'ยังไม่คืน'],
                'จำนวน': [total_transactions, fully_returned_count, partial_returned_count, not_returned_count]
            }
            summary_df = pd.DataFrame(summary_data)
            summary_df.to_excel(writer, sheet_name='สรุป', index=False)
        
        output.seek(0)
        
        # ดาวน์โหลด Excel
        st.download_button(
            label="💾 ดาวน์โหลดรายงาน (Excel)",
            data=output.getvalue(),
            file_name=f"รายงานเบิกเครื่องมือแพทย์_{datetime.now().strftime('%Y-%m-%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        # ดาวน์โหลด CSV
        csv_simple = df_export.to_csv(index=False, encoding='utf-8-sig')
        st.download_button(
            label="📄 ดาวน์โหลดรายงาน (CSV)",
            data=csv_simple,
            file_name=f"medical_equipment_report_{datetime.now().strftime('%Y-%m-%d')}.csv",
            mime="text/csv"
        )
    
    else:
        st.info("ยังไม่มีรายการเบิกเครื่องมือ")

# หน้าจัดการระบบ
elif menu == "⚙️ จัดการระบบ":
    st.header("⚙️ จัดการระบบ")
    
    tab1, tab2, tab3, tab4 = st.tabs(["เพิ่มเครื่องมือ", "แก้ไขเครื่องมือ", "ลบข้อมูล", "ฐานข้อมูล"])
    
    with tab1:
        st.subheader("เพิ่มเครื่องมือใหม่")
        
        with st.form("add_equipment"):
            col1, col2 = st.columns(2)
            
            with col1:
                new_id = st.text_input("รหัสเครื่องมือ", placeholder="เช่น EQ006")
                new_name = st.text_input("ชื่อเครื่องมือ", placeholder="ชื่อเครื่องมือแพทย์")
            
            with col2:
                new_category = st.text_input("หมวดหมู่", placeholder="หมวดหมู่เครื่องมือ")
                col_qty, col_unit = st.columns(2)
                with col_qty:
                    new_quantity = st.number_input("จำนวน", min_value=0, value=1)
                with col_unit:
                    new_unit = st.text_input("หน่วย", placeholder="เช่น เครื่อง, อัน")
            
            if st.form_submit_button("เพิ่มเครื่องมือ", type="primary"):
                if new_id and new_name and new_category and new_unit:
                    if add_equipment(new_id, new_name, new_category, new_quantity, new_unit):
                        st.success("✅ เพิ่มเครื่องมือสำเร็จ!")
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error("❌ รหัสเครื่องมือซ้ำ!")
                else:
                    st.error("❌ กรุณากรอกข้อมูลให้ครบถ้วน!")
    
    with tab2:
        st.subheader("แก้ไขจำนวนเครื่องมือ")
        
        df_equipment = load_equipment()
        if not df_equipment.empty:
            equipment_options = [f"{row['id']} - {row['name']}" for _, row in df_equipment.iterrows()]
            equipment_to_edit = st.selectbox(
                "เลือกเครื่องมือที่ต้องการแก้ไข",
                equipment_options
            )
            
            if equipment_to_edit:
                equipment_id = equipment_to_edit.split(" - ")[0]
                equipment_row = df_equipment[df_equipment['id'] == equipment_id].iloc[0]
                
                new_qty = st.number_input(
                    f"จำนวนใหม่ (ปัจจุบัน: {equipment_row['quantity']} {equipment_row['unit']})",
                    min_value=0,
                    value=int(equipment_row['quantity'])
                )
                
                if st.button("อัพเดทจำนวน", type="primary"):
                    update_equipment_quantity(equipment_id, new_qty)
                    st.success("✅ อัพเดทจำนวนสำเร็จ!")
                    st.cache_data.clear()
                    st.rerun()
    
    with tab3:
        st.subheader("ลบข้อมูล")
        st.warning("⚠️ การลบข้อมูลไม่สามารถย้อนกลับได้!")
        
        if st.button("🗑️ ลบรายการเบิกทั้งหมด", type="secondary"):
            clear_all_transactions()
            st.success("✅ ลบรายการเบิกและประวัติการคืนทั้งหมดแล้ว!")
            st.cache_data.clear()
            st.rerun()
    
    with tab4:
        st.subheader("📊 ข้อมูลฐานข้อมูล")
        
        # แสดงข้อมูลฐานข้อมูล
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        
        try:
            # ขนาดไฟล์ฐานข้อมูล
            if os.path.exists(DB_PATH):
                db_size = os.path.getsize(DB_PATH) / 1024  # KB
                st.metric("ขนาดฐานข้อมูล", f"{db_size:.2f} KB")
            else:
                st.metric("ขนาดฐานข้อมูล", "ไม่พบไฟล์")
            
            # จำนวนตาราง
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**ตารางในฐานข้อมูล:**")
                for table in tables:
                    cursor.execute(f"SELECT COUNT(*) FROM {table[0]}")
                    count = cursor.fetchone()[0]
                    st.write(f"- {table[0]}: {count} รายการ")
            
            with col2:
                # แสดงโครงสร้างตาราง
                st.write("**โครงสร้างตาราง transactions:**")
                cursor.execute("PRAGMA table_info(transactions)")
                trans_info = cursor.fetchall()
                for info in trans_info:
                    st.write(f"- {info[1]} ({info[2]})")
        finally:
            conn.close()
        
        # ปุ่มสำรองข้อมูล
        st.markdown("---")
        st.subheader("💾 สำรองข้อมูล")
        
        # อ่านไฟล์ฐานข้อมูล
        if os.path.exists(DB_PATH):
            with open(DB_PATH, 'rb') as f:
                db_data = f.read()
            
            st.download_button(
                label="📥 ดาวน์โหลดไฟล์ฐานข้อมูล",
                data=db_data,
                file_name=f"medical_equipment_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db",
                mime="application/octet-stream"
            )
        else:
            st.error("ไม่พบไฟล์ฐานข้อมูล")
        
        # อัพโหลดไฟล์สำรอง
        st.markdown("---")
        st.subheader("📤 กู้คืนข้อมูล")
        st.warning("⚠️ การกู้คืนจะเขียนทับข้อมูลปัจจุบัน!")
        
        uploaded_db = st.file_uploader(
            "อัพโหลดไฟล์ฐานข้อมูลสำรอง", 
            type=['db']
        )
        
        if uploaded_db is not None:
            if st.button("🔄 กู้คืนข้อมูล", type="secondary"):
                try:
                    # สำรองไฟล์เดิม
                    if os.path.exists(DB_PATH):
                        import shutil
                        backup_path = f'data/medical_equipment_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
                        shutil.copy(DB_PATH, backup_path)
                    
                    # เขียนไฟล์ใหม่
                    with open(DB_PATH, 'wb') as f:
                        f.write(uploaded_db.read())
                    
                    st.success("✅ กู้คืนข้อมูลสำเร็จ!")
                    st.cache_data.clear()
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"❌ เกิดข้อผิดพลาด: {str(e)}")

# Footer
st.markdown("---")
st.markdown("💡 **คำแนะนำ:** ระบบใหม่รองรับการคืนเครื่องมือแบบบางส่วน QR Code เดิมยังใช้งานได้จนกว่าจะคืนครบ")
st.markdown("🔧 **พัฒนาโดย:** ระบบจัดการเครื่องมือแพทย์ (Version 2.0)")
st.markdown("🗄️ **ฐานข้อมูล:** SQLite")

# แสดงสถานะการเชื่อมต่อฐานข้อมูล
try:
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.close()
    st.sidebar.success("🟢 เชื่อมต่อฐานข้อมูลสำเร็จ")
except Exception as e:
    st.sidebar.error(f"🔴 ไม่สามารถเชื่อมต่อฐานข้อมูลได้: {str(e)}")
