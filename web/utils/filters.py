import pycountry

# Saç Renkleri (Hair Colors)
hair_color_dict = {  
"OTHD": "Diğer (Tanımlanmamış renk veya tarz)",
"BROD": "Koyu Kahverengi / Rasta (Dreadlocks)",    
"BLA": "Siyah",
"BAL": "Kel / Saçsız",
"BLK": "Siyah",
"BLN": "Sarışın",
"BRO": "Kahverengi",
"GRY": "Gri",
"RED": "Kızıl",
"SDY": "Kumral",
"WHI": "Beyaz",
"YELB": "Açık Sarı / Platin Sarışın"
}

# Göz Renkleri (Eye Colors)
eye_color_dict = {
"OTHD": "Diğer (Tanımlanmamış renk veya tarz)",
"BROD": "Koyu Kahverengi / Rasta (Dreadlocks)",
"BLA": "Siyah",
"BLK": "Siyah",
"BLU": "Mavi",
"BRO": "Kahverengi",
"GRN": "Yeşil",
"GRY": "Gri",
"HAZ": "Ela",
"MAR": "Kestane / Maron",
"MUL": "Çok renkli (Heterokromi)"
}

def dil_cevir_filter(deger):
    """
    Interpol'den gelen kodu (FRE, ENG) pycountry ile adına çevirir.
    """
    if not deger:
        return "Not Known"

    codes = str(deger).replace("[", "").replace("]", "").replace("'", "").replace('"', "")
    codes = codes.split(',')
    languages = []

    for code in codes:
        code = code.strip() #Boşlukları ortadan kaldır.
        try:
            language = pycountry.languages.get(alpha_3=code)
            if language:
                languages.append(language.name)
            else:
                languages.append(code)
        except:
            languages.append(code)

    return ', '.join(languages)

def ulke_cevir_filter(code):
    """
    Interpol'den gelen kodu (RU, US) pycountry ile adına çevirir.
    """
    return convert_to_country(code)

def convert_to_country(code_string):
    if not code_string:
        return "Not Known"

    codes = str(code_string).replace("[", "").replace("]", "").replace("'", "").replace('"', "")
    codes = codes.split(',')
    nationalities = []

    for code in codes:
        code = code.strip() #Boşlukları ortadan kaldır.
        try:
            nationality = pycountry.countries.get(alpha_2=code)
            if nationality:
                nationalities.append(nationality.name)
            else:
                nationalities.append(code)
        except:
            nationalities.append(code)

    return ', '.join(nationalities)

def convert_hair_color(code):

    code = str(code).replace("[", "").replace("]", "").replace("'", "").replace('"', "")
    codes = code.split(',')
    colors = []

    for code in codes:
        code = code.strip() #Boşlukları ortadan kaldır.
        try:
            color = hair_color_dict.get(code)
            if color:
                colors.append(color) 
            else:
                colors.append(code)
        except:
            colors.append(code)

    return ', '.join(colors)
    
def convert_eye_color(code):

    code = str(code).replace("[", "").replace("]", "").replace("'", "").replace('"', "")
    codes = code.split(',')
    colors = [] 
    
    for code in codes:
        code = code.strip() #Boşlukları ortadan kaldır.
        try:
            color = eye_color_dict.get(code)
            if color:
                colors.append(color) 
            else:
                colors.append(code)
        except:
            colors.append(code)

    return ', '.join(colors)
    
def init_filters(app):
    """Filtreleri Flask uygulamasına kaydeder."""
    app.jinja_env.filters['dil_cevir'] = dil_cevir_filter
    app.jinja_env.filters['ulke_cevir'] = ulke_cevir_filter
    app.jinja_env.filters['sac_cevir_filter'] = convert_hair_color
    app.jinja_env.filters['goz_cevir_filter'] = convert_eye_color