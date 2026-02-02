import pycountry

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

def init_filters(app):
    """Filtreleri Flask uygulamasına kaydeder."""
    app.jinja_env.filters['dil_cevir'] = dil_cevir_filter
    app.jinja_env.filters['ulke_cevir'] = ulke_cevir_filter