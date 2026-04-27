import streamlit as st
import gspread
import pandas as pd
from pulp import *

# Konfigurasi Halaman Streamlit
st.set_page_config(page_title="Optimasi Menu MBG", layout="wide")
st.title("🍲 Smart Menu Builder Guide (Smart MBG) - Aplikasi Optimasi Menu Makan Bergizi Gratis")

SHEET_URL = "https://docs.google.com/spreadsheets/d/1RaGjYtKssJOH6tS1kDH3x4LXM-DNi4jNJn26RZi-5aM/"

# ==========================================
# FUNGSI CACHE UNTUK MENGAMBIL DATA
# ==========================================
@st.cache_data(ttl=600) # Cache data selama 10 menit agar tidak lemot
def load_data():
    # Membaca kredensial dari st.secrets
    credentials = dict(st.secrets["gcp_service_account"])
    gc = gspread.service_account_from_dict(credentials)
    sh = gc.open_by_url(SHEET_URL)
    
    df_menu = pd.DataFrame(sh.worksheet('menu_master').get_all_records())
    df_recipe = pd.DataFrame(sh.worksheet('recipe_details').get_all_records())
    df_ingredients = pd.DataFrame(sh.worksheet('ingredients').get_all_records())
    df_nutrition = pd.DataFrame(sh.worksheet('nutrition_rules').get_all_records())
    df_leftover = pd.DataFrame(sh.worksheet('leftover_history').get_all_records())
    df_prices = pd.DataFrame(sh.worksheet('local_prices').get_all_records())
    df_inventory = pd.DataFrame(sh.worksheet('inventory_stock').get_all_records())
    
    return df_menu, df_recipe, df_ingredients, df_nutrition, df_leftover, df_prices, df_inventory

# Load data dengan error handling
try:
    with st.spinner('Menghubungkan ke Google Sheets...'):
        df_menu, df_recipe, df_ingredients, df_nutrition, df_leftover, df_prices, df_inventory = load_data()
    st.success("✅ Data berhasil dimuat dari Google Sheets!")
except Exception as e:
    st.error(f"Gagal mengambil data: {e}")
    st.stop()

# ==========================================
# SIDEBAR: PARAMETER INPUT PENGGUNA
# ==========================================
st.sidebar.header("⚙️ Parameter Optimasi")
JENJANG = st.sidebar.selectbox("Tingkat Sekolah", ["SD", "SMP", "SMA"], index=0)
N_SISWA = st.sidebar.number_input("Jumlah Siswa", min_value=1, value=300)
BUDGET_MINGGUAN = st.sidebar.number_input("Anggaran Bahan 6 Hari (Rp)", min_value=100000, value=15000000, step=100000)
PENALTI_GIZI = st.sidebar.number_input("Penalti per poin selisih target gizi (Rp)", min_value=0.0, value=5.0)
PENALTI_LEFTOVER = st.sidebar.number_input("Penalti per 1% Makanan Tersisa (Rp)", min_value=0.0, value=100.0)

# ==========================================
# PRA-PEMROSESAN DATA
# ==========================================
df_recipe_price = pd.merge(df_recipe, df_prices, left_on='nama_bahan', right_on='nama bahan', how='left')
# Ganti 'harga pasar' di bawah ini dengan 'harga koperasi' jika Anda ingin menggunakan harga koperasi
df_recipe_price['biaya_bahan'] = (df_recipe_price['berat_per_porsi'] / 1000) * df_recipe_price['harga pasar']
biaya_per_menu = df_recipe_price.groupby('id_menu')['biaya_bahan'].sum().to_dict()

df_recipe_nutrisi = pd.merge(df_recipe, df_ingredients, left_on='nama_bahan', right_on='nama bahan', how='left')
df_recipe_nutrisi['kcal'] = (df_recipe_nutrisi['berat_per_porsi'] / 100) * df_recipe_nutrisi['kandungan kcal per 100g']
df_recipe_nutrisi['protein'] = (df_recipe_nutrisi['berat_per_porsi'] / 100) * df_recipe_nutrisi['kandungan protein per 100 g']
df_recipe_nutrisi['karbo'] = (df_recipe_nutrisi['berat_per_porsi'] / 100) * df_recipe_nutrisi['kandungan karbohidrat per 100g']
df_recipe_nutrisi['lemak'] = (df_recipe_nutrisi['berat_per_porsi'] / 100) * df_recipe_nutrisi['kandungan lemak per 100g']
nutrisi_per_menu = df_recipe_nutrisi.groupby('id_menu')[['kcal', 'protein', 'karbo', 'lemak']].sum().to_dict('index')

df_menu['biaya'] = df_menu['id_menu'].map(biaya_per_menu).fillna(0)
df_menu['kcal'] = df_menu['id_menu'].map(lambda x: nutrisi_per_menu.get(x, {}).get('kcal', 0))
df_menu['protein'] = df_menu['id_menu'].map(lambda x: nutrisi_per_menu.get(x, {}).get('protein', 0))
df_menu['karbo'] = df_menu['id_menu'].map(lambda x: nutrisi_per_menu.get(x, {}).get('karbo', 0))
df_menu['lemak'] = df_menu['id_menu'].map(lambda x: nutrisi_per_menu.get(x, {}).get('lemak', 0))

leftover_dict = df_leftover.set_index('nama_menu')['persentase_leftover_Li'].to_dict()
df_menu['leftover_pct'] = df_menu['nama_menu'].map(leftover_dict).fillna(0)

id_to_nama = df_menu.set_index('id_menu')['nama_menu'].to_dict()
df_recipe['nama_menu'] = df_recipe['id_menu'].map(id_to_nama)

HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu"]
KATEGORI = ["Menu Pokok", "Protein Hewani", "Protein Nabati", "Sayur", "Buah"]
ZAT_GIZI = ['kcal', 'protein', 'karbo', 'lemak']

target_gizi = df_nutrition[df_nutrition['tingkat sekolah'] == JENJANG].iloc[0]
target = {
    'kcal': target_gizi['kebutuhan kcal'],
    'protein': target_gizi['kebutuhan protein'],
    'karbo': target_gizi['kebutuhan karbohidrat'],
    'lemak': target_gizi['kebutuhan lemak']
}

# ==========================================
# TOMBOL EKSEKUSI
# ==========================================
if st.button("🚀 Buat Jadwal Menu!", type="primary"):
    with st.spinner("Mesin AI sedang menghitung jutaan kombinasi menu..."):
        model = LpProblem("Optimasi_MBG_6Hari", LpMinimize)

        menu_list = df_menu['nama_menu'].tolist()
        x = LpVariable.dicts("pilih", (menu_list, HARI), cat='Binary')
        shortage = LpVariable.dicts("kekurangan", (ZAT_GIZI, HARI), lowBound=0, cat='Continuous')

        total_biaya = lpSum([df_menu[df_menu['nama_menu'] == i]['biaya'].values[0] * N_SISWA * x[i][t] for i in menu_list for t in HARI])
        penalti_leftover = lpSum([(df_menu[df_menu['nama_menu'] == i]['leftover_pct'].values[0] * 100) * PENALTI_LEFTOVER * x[i][t] for i in menu_list for t in HARI])
        penalti_gizi = lpSum([shortage[k][t] * PENALTI_GIZI for k in ZAT_GIZI for t in HARI])

        model += total_biaya + penalti_leftover + penalti_gizi

        # --- CONSTRAINTS ---
        for t in HARI:
            for kat in KATEGORI:
                menu_kategori = df_menu[df_menu['kategori'] == kat]['nama_menu'].tolist()
                model += lpSum([x[i][t] for i in menu_kategori]) == 1

            for k in ZAT_GIZI:
                kandungan_terpilih = lpSum([df_menu[df_menu['nama_menu'] == i][k].values[0] * x[i][t] for i in menu_list])
                model += kandungan_terpilih >= 0.4 * target[k] # Hard limit 40-80%
                model += kandungan_terpilih + shortage[k][t] >= 0.9 * target[k] # Soft limit 90-100%
                
                # Batasan Karbohidrat minimal 50 gram
                if k == 'karbo':
                    model += kandungan_terpilih >= 50

            metode_list = df_menu['metode_masak'].unique()
            for m in metode_list:
                if m != "Tanpa Masak":
                    menu_metode = df_menu[df_menu['metode_masak'] == m]['nama_menu'].tolist()
                    model += lpSum([x[i][t] for i in menu_metode]) <= 1

        model += total_biaya <= BUDGET_MINGGUAN

        for i in menu_list:
            model += lpSum([x[i][t] for t in HARI]) <= 2

        # Kombinasi Protein Hewani dan Nabati tidak boleh sama
        menu_hewani = df_menu[df_menu['kategori'] == 'Protein Hewani']['nama_menu'].tolist()
        menu_nabati = df_menu[df_menu['kategori'] == 'Protein Nabati']['nama_menu'].tolist()
        for h in menu_hewani:
            for n in menu_nabati:
                for i in range(len(HARI)):
                    for j in range(i + 1, len(HARI)):
                        model += x[h][HARI[i]] + x[n][HARI[i]] + x[h][HARI[j]] + x[n][HARI[j]] <= 3

        # Batas Stok Inventory
        bahan_unik_inventory = df_inventory['nama_bahan'].unique()
        for bahan in bahan_unik_inventory:
            row_stok = df_inventory[df_inventory['nama_bahan'] == bahan].iloc[0]
            batas_stok_kg = row_stok['stok_saat_ini'] - row_stok['buffer_stock']
            penggunaan_bahan = lpSum([
                (df_recipe[(df_recipe['nama_bahan'] == bahan) & (df_recipe['nama_menu'] == i)]['berat_per_porsi'].sum() / 1000) 
                * N_SISWA * x[i][t] for i in menu_list for t in HARI
            ])
            model += penggunaan_bahan <= batas_stok_kg

        # Solve Model
        model.solve(PULP_CBC_CMD(msg=0))

        if LpStatus[model.status] == 'Optimal':
            st.success("✨ JADWAL MENU BERHASIL DIBUAT!")
            
            jadwal_utama, jadwal_detail = [], []
            for t in HARI:
                menu_hari_ini = [i for i in menu_list if value(x[i][t]) == 1]
                menu_terurut, berat_per_kategori = [], []

                for kat in KATEGORI:
                    for m in menu_hari_ini:
                        if df_menu[df_menu['nama_menu'] == m]['kategori'].values[0] == kat:
                            menu_terurut.append(m)
                            id_m = df_menu[df_menu['nama_menu'] == m]['id_menu'].values[0]
                            berat = df_recipe[df_recipe['id_menu'] == id_m]['berat_per_porsi'].sum()
                            berat_per_kategori.append(f"{berat:.0f}g")
                            break

                biaya_hari = sum([df_menu[df_menu['nama_menu'] == m]['biaya'].values[0] * N_SISWA for m in menu_hari_ini])
                tot_kcal = sum([df_menu[df_menu['nama_menu'] == m]['kcal'].values[0] for m in menu_hari_ini])
                tot_karbo = sum([df_menu[df_menu['nama_menu'] == m]['karbo'].values[0] for m in menu_hari_ini])
                tot_protein = sum([df_menu[df_menu['nama_menu'] == m]['protein'].values[0] for m in menu_hari_ini])
                tot_lemak = sum([df_menu[df_menu['nama_menu'] == m]['lemak'].values[0] for m in menu_hari_ini])

                jadwal_utama.append([t] + menu_terurut + [f"Rp {biaya_hari:,.0f}"])
                jadwal_detail.append([t] + berat_per_kategori + [f"{tot_kcal:.1f}", f"{tot_karbo:.1f}", f"{tot_protein:.1f}", f"{tot_lemak:.1f}"])

            st.subheader("📋 Tabel 1: Daftar Menu dan Biaya Harian")
            df_utama = pd.DataFrame(jadwal_utama, columns=["Hari"] + KATEGORI + ["Biaya Harian"])
            st.dataframe(df_utama, use_container_width=True)
            
            st.subheader("⚖️ Tabel 2: Detail Berat Porsi & Akumulasi Gizi")
            kolom_detail = ["Hari", "Berat Pokok", "Berat P.Hewani", "Berat P.Nabati", "Berat Sayur", "Berat Buah", "Total Kcal", "Karbo (g)", "Protein (g)", "Lemak (g)"]
            df_detail = pd.DataFrame(jadwal_detail, columns=kolom_detail)
            st.dataframe(df_detail, use_container_width=True)

            st.metric(label="Total Biaya 6 Hari", value=f"Rp {value(total_biaya):,.0f}")

        else:
            st.error("❌ Model Infeasible: Tidak ada kombinasi menu yang memenuhi syarat.")
            st.info("Saran perbaikan: 1) Naikkan Budget, 2) Periksa stok bahan di gudang untuk jumlah siswa tersebut, atau 3) Longgarkan target gizi.")
