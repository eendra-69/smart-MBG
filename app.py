import streamlit as st
import gspread
import random
import pandas as pd
from pulp import *

# Konfigurasi Halaman Streamlit
st.set_page_config(page_title="Optimasi Menu MBG", layout="wide")
st.title("🍲 Smart Menu Builder Guide (Smart MBG) - Aplikasi Optimasi Menu MBG")

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
    with st.spinner('Menghubungkan ke Database...'):
        df_menu, df_recipe, df_ingredients, df_nutrition, df_leftover, df_prices, df_inventory = load_data()
    st.success("✅ Data berhasil dimuat dari Database")
except Exception as e:
    st.error(f"Gagal mengambil data: {e}")
    st.stop()

# ==========================================
# SIDEBAR: PARAMETER INPUT PENGGUNA
# ==========================================
st.sidebar.header("⚙️ Parameter Optimasi")

# FITUR BARU: Pemilihan Jumlah Hari
JUMLAH_HARI = st.sidebar.selectbox("Jumlah Hari Penyajian", [4, 5, 6], index=2, help="Pilih berapa hari menu disajikan dalam seminggu.")

JENJANG = st.sidebar.selectbox("Tingkat Sekolah", ["SD", "SMP", "SMA"], index=0)
N_SISWA = st.sidebar.number_input("Jumlah Siswa", min_value=1, value=300)

# Default budget disesuaikan otomatis berdasarkan jumlah hari (Asumsi dasar 2.5jt per hari)
default_budget = int(JUMLAH_HARI * 2500000)
BUDGET_MINGGUAN = st.sidebar.number_input(f"Anggaran {JUMLAH_HARI} Hari (Rp)", min_value=100000, value=default_budget, step=100000)

PENALTI_GIZI = st.sidebar.number_input("Penalti per poin selisih target gizi (Rp)", min_value=0.0, value=10.0)
PENALTI_LEFTOVER = st.sidebar.number_input("Penalti per 1% sisa makanan (Rp)", min_value=0.0, value=100.0)

# ==========================================
# PRA-PEMROSESAN DATA
# ==========================================
df_recipe_price = pd.merge(df_recipe, df_prices, left_on='nama_bahan', right_on='nama bahan', how='left')
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

# PENGATURAN HARI DINAMIS
HARI_FULL = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu"]
HARI = HARI_FULL[:JUMLAH_HARI] # Otomatis memotong array hari sesuai input pengguna

KATEGORI = ["Menu Pokok", "Protein Hewani", "Protein Nabati", "Sayur", "Buah"]
ZAT_GIZI = ['kcal', 'protein', 'karbo', 'lemak']

target_gizi = df_nutrition[df_nutrition['tingkat sekolah'] == JENJANG].iloc[0]
target = {
    'kcal': target_gizi['kebutuhan kcal'],
    'protein': target_gizi['kebutuhan protein'],
    'karbo': target_gizi['kebutuhan karbohidrat'],
    'lemak': target_gizi['kebutuhan lemak']
}

# ================================
# PRECOMPUTE SUPER FAST LOOKUP
# ================================

menu_list = df_menu['nama_menu'].tolist()

biaya_dict = df_menu.set_index('nama_menu')['biaya'].to_dict()
leftover_dict = df_menu.set_index('nama_menu')['leftover_pct'].to_dict()

# Nutrisi dictionary
nutrisi_dict = df_menu.set_index('nama_menu')[['kcal','protein','karbo','lemak']].to_dict('index')

# Kategori mapping
kategori_dict = df_menu.set_index('nama_menu')['kategori'].to_dict()

# Metode masak
metode_dict = df_menu.set_index('nama_menu')['metode_masak'].to_dict()

# Group kategori → menu list
kategori_menu = {
    kat: df_menu[df_menu['kategori'] == kat]['nama_menu'].tolist()
    for kat in KATEGORI
}

# Group metode → menu list
metode_menu = {
    m: df_menu[df_menu['metode_masak'] == m]['nama_menu'].tolist()
    for m in df_menu['metode_masak'].unique()
}

# Inventory usage precompute
bahan_usage = {}
for bahan in df_inventory['nama_bahan'].unique():
    usage_per_menu = {}
    for i in menu_list:
        total = df_recipe[
            (df_recipe['nama_bahan'] == bahan) & 
            (df_recipe['nama_menu'] == i)
        ]['berat_per_porsi'].sum()
        if total > 0:
            usage_per_menu[i] = total / 1000
    bahan_usage[bahan] = usage_per_menu

# ==========================================
# 🤖 AGEN 1: WASTE & SENTIMENT AGENT
# ==========================================
class WasteSentimentAgent:
    def __init__(self, threshold_waste=20.0, penalty_multiplier=1.5):
        """
        threshold_waste: Batas maksimal persentase sisa makanan yang dapat ditoleransi (Default 20%).
        penalty_multiplier: Faktor pengali hukuman jika sisa makanan melebihi batas (Default 1.5x lipat).
        """
        self.threshold_waste = threshold_waste
        self.penalty_multiplier = penalty_multiplier

    def analyze(self, df_leftover, base_leftover_dict):
        """
        Menganalisis data sisa makanan dan memodifikasi bobot penalti untuk optimasi matematis.
        Mengembalikan: dict penalti yang sudah disesuaikan dan laporan naratif.
        """
        adjusted_leftover_dict = base_leftover_dict.copy()
        laporan_naratif = "📊 **Laporan Agen Analis Sisa Makanan:**\n\n"
        
        # Filter menu yang tidak disukai (sisa di atas ambang batas)
        high_waste_menus = df_leftover[df_leftover['persentase_leftover_Li'] > self.threshold_waste]
        
        if high_waste_menus.empty:
            laporan_naratif += "✅ Seluruh menu disajikan dengan baik minggu lalu (Sisa < 20%). Tidak ada penalti tambahan yang diterapkan."
        else:
            laporan_naratif += f"⚠️ Peringatan: Ditemukan {len(high_waste_menus)} menu dengan tingkat sisa di atas {self.threshold_waste}%!\n"
            
            for index, row in high_waste_menus.iterrows():
                nama = row['nama_menu']
                sisa = row['persentase_leftover_Li']
                
                # Modifikasi Hukuman: Lipat gandakan persentase sisanya di mata AI (PuLP)
                # Agar algoritma AI merasa menu ini "sangat mahal" untuk dipilih
                adjusted_leftover_dict[nama] = adjusted_leftover_dict[nama] * self.penalty_multiplier
                
                laporan_naratif += f"- **{nama}**: Sisa {sisa}%. 🔨 *Tindakan: Penalti dilipatgandakan {self.penalty_multiplier}x.*\n"
                
            laporan_naratif += "\n*🍲Menu di atas akan sangat dihindari untuk jadwal berikutnya.*"
            
        return adjusted_leftover_dict, laporan_naratif

# Inisiasi Agen
waste_agent = WasteSentimentAgent(threshold_waste=20.0, penalty_multiplier=1.5)

# ==========================================
# 📈 AGEN 2: MARKET & PROCUREMENT AGENT
# ==========================================
class MarketProcurementAgent:
    def __init__(self, simulation_mode=True):
        self.simulation_mode = simulation_mode

    def fetch_real_time_prices(self, df_prices):
        updated_prices = df_prices.copy()
        
        # Buat kolom baru untuk menyimpan harga pemenang dan sumbernya
        updated_prices['harga_final'] = 0.0 
        updated_prices['sumber_pilihan'] = ""
        
        laporan_naratif = "🌐 **Laporan Agen Pembelian:**\n\n"
        laporan_naratif += "🔍 *Membandingkan harga Vendor Lokal, Koperasi, dan Pasar Induk....*\n\n"
        
        perubahan_harga = []
        
        for index, row in updated_prices.iterrows():
            bahan = row['nama bahan']
            
            harga_Pasar_Induk = float(row.get('harga pasar induk', row.get('harga pasar', 0)))
            harga_vendor_lokal = float(row.get('harga vendor lokal', harga_Pasar_Induk * 1.05)) 
            harga_koperasi = float(row.get('harga koperasi', harga_Pasar_Induk * 1.02))
            
            peluang = random.random()
            if peluang < 0.25:
                harga_scraping = harga_Pasar_Induk * random.uniform(0.80, 0.95)
            elif peluang < 0.45:
                harga_scraping = harga_Pasar_Induk * random.uniform(1.10, 1.30)
            else:
                harga_scraping = harga_Pasar_Induk * random.uniform(0.98, 1.02)
            
            kandidat = {
                "Vendor Lokal": harga_vendor_lokal,
                "Koperasi": harga_koperasi,
                "Pasar Induk": harga_scraping
            }
            
            kandidat_valid = {k: v for k, v in kandidat.items() if v > 0}
            
            if kandidat_valid:
                pemenang_sumber = min(kandidat_valid, key=kandidat_valid.get)
                harga_termurah = kandidat_valid[pemenang_sumber]
            else:
                pemenang_sumber = "Vendor Lokal" # Default fallback
                harga_termurah = 0
                
            # Simpan harga pemenang DAN SUMBERNYA
            updated_prices.at[index, 'harga_final'] = harga_termurah
            updated_prices.at[index, 'sumber_pilihan'] = pemenang_sumber # <--- BARIS BARU INI DITAMBAHKAN
            
            perubahan_harga.append(f"✅ **{bahan}**: Rp {harga_termurah:,.0f}/kg ➔ *Diambil dari {pemenang_sumber}*")

        if perubahan_harga:
            laporan_naratif += "\n".join(perubahan_harga[:7])
            if len(perubahan_harga) > 7:
                laporan_naratif += f"\n*...serta {len(perubahan_harga) - 7} bahan lain berhasil dihemat.*"
            laporan_naratif += "\n\n💰 *Harga termurah otomatis diterapkan ke mesin perhitungan.*"
        else:
            laporan_naratif += "✅ *Gagal mendapatkan perbandingan harga.*"
            
        return updated_prices, laporan_naratif

# Inisiasi Agen Pasar
market_agent = MarketProcurementAgent()

# ==========================================
# TOMBOL EKSEKUSI
# ==========================================
if st.button("🚀 Buat Jadwal Menu!", type="primary"):
   with st.spinner("Para Analis sedang berdiskusi dan mesin AI sedang menghitung kombinasi menu..."):
        
       # --- (BAGIAN BARU: EKSEKUSI MULTI-AGENT) ---
        kolom_agen1, kolom_agen2 = st.columns(2)
        
        # 1. JALANKAN AGEN SISA MAKANAN (Waste Agent)
        adjusted_leftover_dict, laporan_waste = waste_agent.analyze(df_leftover, leftover_dict)
        with kolom_agen1:
            st.info(laporan_waste)
            
        # 2. JALANKAN AGEN INTELIJEN PASAR (Market Agent)
        updated_df_prices, laporan_pasar = market_agent.fetch_real_time_prices(df_prices)
        with kolom_agen2:
            st.success(laporan_pasar)
            
        # ----------------------------------------------------
        # 3. LETAK KODE RE-KALKULASI BIAYA ADALAH DI SINI
        # ----------------------------------------------------
        # AI merakit ulang harga resep menggunakan HARGA FINAL (Termurah) dari agen
        df_recipe_price_new = pd.merge(df_recipe, updated_df_prices, left_on='nama_bahan', right_on='nama bahan', how='left')
        df_recipe_price_new['biaya_bahan'] = (df_recipe_price_new['berat_per_porsi'] / 1000) * df_recipe_price_new['harga_final']
        
        biaya_per_menu_new = df_recipe_price_new.groupby('id_menu')['biaya_bahan'].sum().to_dict()
        
        # Update dictionary biaya yang akan dimasukkan ke otak PuLP
        biaya_dict_dinamis = {}
        for i in menu_list:
            id_m = df_menu[df_menu['nama_menu'] == i]['id_menu'].values[0]
            biaya_dict_dinamis[i] = biaya_per_menu_new.get(id_m, 0)

        # ----------------------------------------------------
        # 4. MULAI OPTIMASI MATEMATIS (PuLP)
        # ----------------------------------------------------
        model = LpProblem(f"Optimasi_MBG_{JUMLAH_HARI}Hari", LpMinimize)

        x = LpVariable.dicts("x", (menu_list, HARI), cat='Binary')
        shortage = LpVariable.dicts("s", (ZAT_GIZI, HARI), lowBound=0)

        # ================================
        # OBJECTIVE FUNCTION 
        # ================================
        model += lpSum(
            # --> PERHATIKAN: Sekarang menggunakan biaya_dict_dinamis
            biaya_dict_dinamis[i] * N_SISWA * x[i][t]
            + adjusted_leftover_dict[i] * 100 * PENALTI_LEFTOVER * x[i][t] 
            for i in menu_list for t in HARI
        ) + lpSum(
            shortage[k][t] * PENALTI_GIZI
            for k in ZAT_GIZI for t in HARI
        )

        # ================================
        # CONSTRAINTS
        # ================================

        for t in HARI:

            # 1. Kategori constraint
            for kat in KATEGORI:
                model += lpSum(x[i][t] for i in kategori_menu[kat]) == 1

            # 2. Nutrisi constraint
            for k in ZAT_GIZI:
                kandungan = lpSum(nutrisi_dict[i][k] * x[i][t] for i in menu_list)

                model += kandungan >= 0.6 * target[k]
                model += kandungan + shortage[k][t] >= target[k]

                if k == 'karbo':
                    model += kandungan >= 40

            # 3. Metode masak constraint
            for m, menus in metode_menu.items():
                if m != "Tanpa Masak":
                    model += lpSum(x[i][t] for i in menus) <= 2


	    # 4. Budget constraint (PASTIKAN MENGGUNAKAN biaya_dict_dinamis JUGA)
            model += lpSum(
            	biaya_dict_dinamis[i] * N_SISWA * x[i][t]
            	for i in menu_list for t in HARI
        ) <= BUDGET_MINGGUAN	


        # 5. Maksimal muncul 2x
        for i in menu_list:
            model += lpSum(x[i][t] for t in HARI) <= 2

        # 7. Pembatas: Menu yang sama tidak boleh muncul berurutan hari
        for i in menu_list:
            for d in range(len(HARI) - 1):
                hari_ini = HARI[d]
                besok = HARI[d+1]
                model += x[i][hari_ini] + x[i][besok] <= 1

        # 6. Inventory constraint (SUPER OPTIMIZED)
        for bahan, usage_dict in bahan_usage.items():

            row = df_inventory[df_inventory['nama_bahan'] == bahan].iloc[0]
            batas = row['stok_saat_ini'] - row['buffer_stock']

            model += lpSum(
                usage_dict.get(i, 0) * N_SISWA * x[i][t]
                for i in menu_list for t in HARI
            ) <= batas

        # Solve Model
        model.solve(PULP_CBC_CMD(msg=0))

        if LpStatus[model.status] == 'Optimal':
            st.success(f"✨ JADWAL MENU UNTUK {JUMLAH_HARI} HARI BERHASIL DIBUAT!")
            
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
            kolom_detail = ["Hari", "Berat M.Pokok", "Berat P.Hewani", "Berat P.Nabati", "Berat Sayur", "Berat Buah", "Total Kcal", "Karbo (g)", "Protein (g)", "Lemak (g)"]
            df_detail = pd.DataFrame(jadwal_detail, columns=kolom_detail)
            st.dataframe(df_detail, use_container_width=True)

			# ==========================================
            # TABEL 3: REKAP BELANJA BAHAN PER KANDIDAT / SUMBER
            # ==========================================
            st.subheader("🛒 Tabel 3: Daftar Belanja Harian (per Pemasok)")
            st.markdown("Berikut adalah instruksi pembelian otomatis yang telah dioptimasi:")
            
            data_belanja = []
            
            # Buat kamus (dictionary) cepat untuk mencari siapa supplier bahan ini dan harganya
            sumber_dict = updated_df_prices.set_index('nama bahan')['sumber_pilihan'].to_dict()
            harga_dict = updated_df_prices.set_index('nama bahan')['harga_final'].to_dict()
            
            for t in HARI:
                menu_hari_ini = [i for i in menu_list if value(x[i][t]) == 1]
                
                # Cari resep untuk setiap menu yang terpilih hari ini
                for m in menu_hari_ini:
                    resep_m = df_recipe[df_recipe['nama_menu'] == m]
                    for _, row in resep_m.iterrows():
                        bahan = row['nama_bahan']
                        berat_per_porsi_g = row['berat_per_porsi']
                        
                        # Hitung kebutuhan
                        kebutuhan_kg = (berat_per_porsi_g * N_SISWA) / 1000 
                        
                        # Ambil data dari hasil agen
                        sumber = sumber_dict.get(bahan, "Vendor Lokal") # Default jika tidak ada
                        harga_per_kg = harga_dict.get(bahan, 0)
                        estimasi_biaya = kebutuhan_kg * harga_per_kg
                        
                        data_belanja.append({
                            "Nama Bahan": bahan,
                            "Hari": t,
                            "Sumber Pemasok": sumber,
                            "Kebutuhan (Kg)": kebutuhan_kg,
                            "Estimasi Biaya": estimasi_biaya
                        })
            
            if data_belanja:
                df_belanja = pd.DataFrame(data_belanja)
                
                # Mendapatkan daftar kandidat unik yang terpilih (misal: hanya Koperasi dan Pasar)
                sumber_terpilih = df_belanja['Sumber Pemasok'].unique()
                
                # Looping untuk membuat tabel terpisah untuk setiap kandidat
                for pemasok in sumber_terpilih:
                    with st.expander(f"📦 Daftar Belanja: {pemasok}", expanded=True):
                        # Filter data khusus untuk pemasok ini
                        df_sub = df_belanja[df_belanja['Sumber Pemasok'] == pemasok]
                        
                        # Buat tabel pivot
                        df_pivot_belanja = df_sub.groupby(['Nama Bahan', 'Hari'])['Kebutuhan (Kg)'].sum().unstack(fill_value=0)
                        
                        # Pastikan urutan hari
                        kolom_hari_ada = [hari for hari in HARI if hari in df_pivot_belanja.columns]
                        df_pivot_belanja = df_pivot_belanja[kolom_hari_ada]
                        
                        # Tambahkan Total Kebutuhan
                        df_pivot_belanja[f'Total {JUMLAH_HARI} Hari (Kg)'] = df_pivot_belanja.sum(axis=1)
                        
                        # Tampilkan ke layar
                        st.dataframe(df_pivot_belanja.style.format("{:.2f}"), use_container_width=True)
                        
                        # Hitung tagihan per kandidat
                        total_tagihan = df_sub['Estimasi Biaya'].sum()
                        st.info(f"💵 **Estimasi Tagihan ke {pemasok} minggu ini: Rp {total_tagihan:,.0f}**")
                        
            else:
                st.info("Data resep tidak ditemukan untuk membuat daftar belanja.")
            # ==========================================
            # AKHIR TABEL 3
            # ==========================================

            # Menghitung total biaya dari menu yang final terpilih
            total_biaya_aktual = sum([df_menu[df_menu['nama_menu'] == i]['biaya'].values[0] * N_SISWA for i in menu_list for t in HARI if value(x[i][t]) == 1])
            
            # Teks metric otomatis
            st.metric(label=f"Total Biaya {JUMLAH_HARI} Hari", value=f"Rp {total_biaya_aktual:,.0f}")

        else:
            st.error("❌ Model Infeasible: Tidak ada kombinasi menu yang memenuhi syarat.")
            st.info("Saran perbaikan: 1) Naikkan Budget, 2) Periksa stok bahan di gudang untuk jumlah siswa tersebut, atau 3) Longgarkan target gizi.")
