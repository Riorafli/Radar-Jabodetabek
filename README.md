# Golden Eye

Berita, promo, tempat viral, saham, game, dan pantauan berita China untuk Jabodetabek, dalam satu halaman dan bisa dipilah per kota atau per zona.

**Lihat langsung:** https://riorafli.github.io/Radar-Jabodetabek/

## Keunggulan

### Lokal sampai level zona
- Semua konten bisa dipilah per **14 kota/kabupaten** dan **20 zona populer** (Kemang, BSD, Margonda, dan lainnya).
- Tombol **"Dekat saya"** memakai lokasi pengunjung untuk langsung menampilkan area terdekat dan mengurutkan promo dari yang paling dekat.

### Berita yang cepat dipahami
- **Key points** otomatis: 2 sampai 4 poin singkat per berita, ditulis ulang oleh AI dengan kata-kata sendiri, jadi inti beritanya bisa ditangkap tanpa membuka artikel.
- Selalu ada link ke artikel aslinya. Media yang memasang opt-out AI di robots.txt dihormati dan tidak diringkas.
- **Foto** dari tiap media, dengan tampilan kartu yang tetap rapi di laptop maupun HP.

### Bisa dipercaya
- **Label sumber**: resmi pemerintah, media negara, media swasta, media lokal, atau agregator.
- **Status verifikasi Dewan Pers**, plus filter "Hanya media terverifikasi".
- **Cek hoaks otomatis**: berita yang mirip klaim yang sudah dinyatakan salah oleh TurnBackHoax atau CekFakta.com diberi peringatan dan link ke hasil cek faktanya.

### Dua bahasa
- Tampilan dalam **Bahasa Indonesia** (default) dan **English**, tinggal satu klik.
- Dalam mode English, judul, key points, dan ringkasan berita ikut diterjemahkan, termasuk tab Game, China, dan Saham.

### Lebih dari sekadar berita
- **Promo**: makanan, marketplace, dan cuci gudang, lengkap dengan logo merchant, sisa waktu promo, besar diskon, dan label halal yang hanya dipasang bila ada dasar yang jelas.
- **Viral**: skor tempat yang lagi ramai per zona, dihitung dari lonjakan sebutan di YouTube, berita, dan Reddit, ditambah laporan pengunjung. Ada juga video kuliner populer, pencarian Google yang sedang naik, dan tempat makan baru dari OpenStreetMap.
- **Saham**: IHSG, saham yang paling naik dan turun, grafik harga, dan kode saham atau kripto yang paling banyak diberitakan. Hanya informasi, bukan saran investasi.
- **Game**: berita game dari media Indonesia dan internasional (PC, konsol, mobile, esports, hardware), plus daftar terlaris dan diskon Steam dengan harga rupiah.
- **China**: berita teknologi, bisnis, kebijakan, serta F&B dan franchise dari media China, diterjemahkan otomatis.
- **Peta**: tempat viral, tempat baru, dan lokasi sale dalam satu peta.

### Ringan dan otomatis
- Situs statis tanpa framework. Peta baru dimuat saat tab Peta dibuka, dan ada mode gelap.
- Seluruh data diperbarui sendiri lewat GitHub Actions, tanpa server yang harus dijaga.
- Berjalan sepenuhnya di **layanan gratis** (GitHub, Supabase, Gemini/Groq, YouTube Data API, OpenStreetMap). Data lama dibersihkan otomatis supaya database tetap kecil.

### Main aman
- Hanya mengambil dari sumber yang mengizinkan lewat robots.txt dan syarat layanannya. Marketplace dan media sosial yang melarang scraping tidak disentuh.
- Yang disimpan hanya judul, ringkasan pendek, dan link, bukan artikel utuh.
- Tidak menyimpan data pribadi pengunjung.
- Tidak ada kunci rahasia di kode. Database publik hanya bisa dibaca, tidak bisa diubah.
