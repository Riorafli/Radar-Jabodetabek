"""Tag food promos with `jenis` (makanan / minuman / campuran) and `halal`.
python -m pipeline.food_tags   (runs hourly after the promo collectors)

Halal is never guessed. It is only set from explicit signals:
  - pork / alcohol words in the promo text          -> non_halal
  - the word "halal" in the promo text              -> halal
  - brand marked `halal: true|false` in brands.yaml -> halal / non_halal
Everything else stays NULL (the site shows no label).
"""
from pipeline.common import db, load_config, log
from pipeline.entities import BrandMatcher
from pipeline.geocode import normalize

MAKANAN = [
    "makan", "makanan", "meal", "combo", "paket", "ayam", "chicken", "burger", "pizza", "nasi", "rice", "mie", "mi",
    "bakmi", "noodle", "ramen", "udon", "sushi", "roti", "bread", "donat", "donut", "kue", "cake", "steak", "sate",
    "dimsum", "bakso", "soto", "rendang", "seafood", "ikan", "udang", "kentang", "fries", "sandwich", "pasta",
    "spaghetti", "snack", "camilan", "dessert", "es krim", "ice cream", "waffle", "croissant", "martabak", "pempek",
    "katsu", "bento", "beef", "daging", "gyoza", "dumpling", "salad", "bebek", "lunch", "dinner", "breakfast",
    "sarapan", "buffet", "all you can eat", "hotpot", "shabu", "yakiniku", "bbq", "grill", "kebab", "restoran",
    "resto", "restaurant", "dining", "bistro", "wings", "nugget", "telur", "egg", "lauk",
]
MINUMAN = [
    "minuman", "minum", "drink", "drinks", "beverage", "kopi", "coffee", "latte", "cappuccino", "americano",
    "espresso", "macchiato", "frappe", "frappuccino", "teh", "tea", "boba", "bubble", "susu", "milk", "jus", "juice",
    "smoothie", "smoothies", "soda", "matcha", "lemonade", "yakult", "kombucha", "cokelat", "chocolate", "es kopi",
    "es teh", "thai tea", "milk tea", "fanta", "cola", "coca cola", "coke", "sprite", "float", "mcfloat", "pepsi",
    "air mineral", "frappe", "chatime", "es campur", "es buah",
]
NON_HALAL = [
    "babi", "pork", "bacon", "ham", "b2", "bpk", "lard", "charsiu", "char siu", "siobak", "samcan", "lapchiong",
    "babi guling", "wine", "beer", "bir", "soju", "whisky", "whiskey", "vodka", "cocktail", "cocktails", "alkohol",
    "alcohol", "liquor", "non halal", "nonhalal", "tidak halal",
]


def _hit(t, words):
    return any(f" {normalize(w).strip()} " in t for w in words)


def jenis_of(teks, brand_jenis=None):
    """Food wins over drink: a burger + cola combo is a meal."""
    t = normalize(teks)
    if _hit(t, MAKANAN):
        return "makanan"
    if _hit(t, MINUMAN):
        return "minuman"
    return brand_jenis or "campuran"


def halal_of(teks, brand_halal=None):
    t = normalize(teks)
    if _hit(t, NON_HALAL):
        return "non_halal"
    if " halal " in t:
        return "halal"
    if brand_halal is True:
        return "halal"
    if brand_halal is False:
        return "non_halal"
    return None


def brand_info(brand, cfg, matcher):
    nama = matcher.canonical(brand or "") or (matcher.find(brand or "")[:1] or [None])[0]
    b = cfg.get(nama, {}) if nama else {}
    return b.get("jenis"), b.get("halal")


def main():
    cfg = {b["nama"]: b for b in load_config("brands").get("brand", [])}
    bm = BrandMatcher()
    with db() as cur:
        cur.execute("""select p.item_id, p.brand, coalesce(p.menu, ''), i.judul, coalesce(p.syarat, ''),
                              coalesce(i.ringkasan, ''), p.jenis, p.halal
                       from promo p join item i on i.id = p.item_id where p.kategori = 'makanan'""")
        rows = cur.fetchall()
        n = 0
        for item_id, brand, menu, judul, syarat, ringkasan, j0, h0 in rows:
            bj, bh = brand_info(brand, cfg, bm)
            teks = " ".join([brand or "", menu, judul, syarat, ringkasan])
            j, h = jenis_of(teks, bj), halal_of(teks, bh)
            if (j, h) != (j0, h0):
                cur.execute("update promo set jenis = %s, halal = %s where item_id = %s", (j, h, item_id))
                n += 1
    log(f"food_tags: {len(rows)} promo makanan, {n} diperbarui")


if __name__ == "__main__":
    main()
