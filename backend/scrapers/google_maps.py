"""
Google Maps scraper using the Outscraper API.
Supports multiple business types, dedup by place_id,
per-platform delivery/reservation column extraction.
"""
import os
from outscraper import ApiClient

# ── Business type query strings ───────────────────────────────────────────────
BUSINESS_TYPE_QUERIES = {
    'restaurants': 'restaurants',
    'cafes':       'cafes coffee shops',
    'bars':        'bars pubs',
    'bakeries':    'bakeries',
    'fast_food':   'fast food',
}

DEFAULT_BUSINESS_TYPES = ['restaurants', 'cafes']

# ── City district expansion ───────────────────────────────────────────────────
# For large cities, Google Maps caps at ~500 results per query.
# We split into districts/boroughs so each sub-query returns a fresh batch.
# All results are deduplicated by place_id afterward.
CITY_DISTRICTS = {
    # Czech Republic
    'prague':  [f'Praha {i}' for i in range(1, 23)],
    'praha':   [f'Praha {i}' for i in range(1, 23)],
    'brno':    ['Brno-střed', 'Brno-sever', 'Brno-jih', 'Brno-východ', 'Brno-západ',
                'Brno-Komín', 'Brno-Židenice', 'Brno-Líšeň', 'Brno-Bystrc',
                'Brno-Bosonohy', 'Brno-Tuřany', 'Brno-Kohoutovice'],
    'ostrava': ['Ostrava-jih', 'Ostrava-město', 'Mariánské Hory', 'Poruba',
                'Hrabůvka', 'Zábřeh', 'Vítkovice', 'Slezská Ostrava'],
    'plzen':   ['Plzeň 1', 'Plzeň 2', 'Plzeň 3', 'Plzeň 4',
                'Plzeň 5', 'Plzeň 6', 'Plzeň 7', 'Plzeň 8', 'Plzeň 9', 'Plzeň 10'],
    # Poland — merged duplicate 'warsaw' entries into one comprehensive list
    'warsaw':  ['Warsaw Śródmieście', 'Warsaw Mokotów', 'Warsaw Praga-Południe',
                'Warsaw Wola', 'Warsaw Ursynów', 'Warsaw Bielany', 'Warsaw Targówek',
                'Warsaw Wilanów', 'Warsaw Białołęka', 'Warsaw Ochota',
                'Warsaw Bemowo', 'Warsaw Żoliborz', 'Warsaw Włochy', 'Warsaw Wesoła'],
    'krakow':  ['Kraków Stare Miasto', 'Kraków Kazimierz', 'Kraków Podgórze',
                'Kraków Krowodrza', 'Kraków Nowa Huta', 'Kraków Bronowice',
                'Kraków Dębniki', 'Kraków Grzegórzki', 'Kraków Prądnik Biały'],
    'cracow':  ['Kraków Stare Miasto', 'Kraków Kazimierz', 'Kraków Podgórze',
                'Kraków Krowodrza', 'Kraków Nowa Huta'],
    # Germany
    'berlin':  ['Berlin Mitte', 'Berlin Prenzlauer Berg', 'Berlin Kreuzberg',
                'Berlin Friedrichshain', 'Berlin Neukölln', 'Berlin Schöneberg',
                'Berlin Charlottenburg', 'Berlin Wedding', 'Berlin Spandau',
                'Berlin Steglitz', 'Berlin Tempelhof', 'Berlin Lichtenberg',
                'Berlin Pankow', 'Berlin Treptow', 'Berlin Köpenick',
                'Berlin Reinickendorf', 'Berlin Zehlendorf', 'Berlin Wilmersdorf'],
    # Austria
    'vienna':  [f'Vienna {d}' for d in [
                'Innere Stadt', 'Leopoldstadt', 'Landstraße', 'Wieden', 'Margareten',
                'Mariahilf', 'Neubau', 'Josefstadt', 'Alsergrund', 'Favoriten',
                'Simmering', 'Meidling', 'Hietzing', 'Penzing', 'Rudolfsheim',
                'Ottakring', 'Hernals', 'Währing', 'Döbling', 'Brigittenau',
                'Floridsdorf', 'Donaustadt', 'Liesing']],
    # Hungary
    'budapest': [f'Budapest {d}. district' for d in range(1, 24)],
    # Slovakia
    'bratislava': ['Bratislava Staré Mesto', 'Bratislava Ružinov', 'Bratislava Nové Mesto',
                   'Bratislava Petržalka', 'Bratislava Dúbravka', 'Bratislava Karlova Ves',
                   'Bratislava Lamač', 'Bratislava Rača', 'Bratislava Vajnory',
                   'Bratislava Devínska Nová Ves'],
    # Romania
    'bucharest': ['Bucharest Sector 1', 'Bucharest Sector 2', 'Bucharest Sector 3',
                  'Bucharest Sector 4', 'Bucharest Sector 5', 'Bucharest Sector 6'],
    # Greece
    'athens':  ['Athens Syntagma', 'Athens Monastiraki', 'Athens Exarcheia',
                'Athens Kolonaki', 'Athens Psirri', 'Athens Koukaki', 'Athens Gazi',
                'Athens Glyfada', 'Athens Piraeus', 'Athens Kifisia',
                'Athens Halandri', 'Athens Marousi'],
}

# ── Country → city list mapping ───────────────────────────────────────────────
# When a user scrapes a country, we query each major city individually (~500
# results each) and deduplicate by place_id.  Keys are lowercase name variants.
COUNTRY_CITIES = {
    # Czech Republic
    'czech republic': [
        'Prague', 'Brno', 'Ostrava', 'Plzeň', 'Liberec', 'Olomouc',
        'Ústí nad Labem', 'České Budějovice', 'Hradec Králové', 'Pardubice',
        'Zlín', 'Havířov', 'Kladno', 'Most', 'Opava', 'Frýdek-Místek',
        'Karviná', 'Jihlava', 'Teplice', 'Děčín', 'Karlovy Vary', 'Chomutov',
        'Přerov', 'Jablonec nad Nisou', 'Prostějov', 'Mladá Boleslav',
        'Třebíč', 'Nový Jičín', 'Česká Lípa', 'Znojmo', 'Vsetín', 'Šumperk',
        'Kolín', 'Trutnov', 'Tábor', 'Litoměřice', 'Cheb', 'Kroměříž',
    ],
    'czechia': [
        'Prague', 'Brno', 'Ostrava', 'Plzeň', 'Liberec', 'Olomouc',
        'Ústí nad Labem', 'České Budějovice', 'Hradec Králové', 'Pardubice',
        'Zlín', 'Havířov', 'Kladno', 'Most', 'Opava', 'Frýdek-Místek',
        'Karviná', 'Jihlava', 'Teplice', 'Děčín', 'Karlovy Vary', 'Chomutov',
        'Přerov', 'Jablonec nad Nisou', 'Prostějov', 'Mladá Boleslav',
        'Třebíč', 'Nový Jičín', 'Česká Lípa', 'Znojmo', 'Vsetín', 'Šumperk',
        'Kolín', 'Trutnov', 'Tábor', 'Litoměřice', 'Cheb', 'Kroměříž',
    ],
    'czech': [
        'Prague', 'Brno', 'Ostrava', 'Plzeň', 'Liberec', 'Olomouc',
        'Ústí nad Labem', 'České Budějovice', 'Hradec Králové', 'Pardubice',
        'Zlín', 'Havířov', 'Kladno', 'Most', 'Opava', 'Frýdek-Místek',
        'Karviná', 'Jihlava', 'Teplice', 'Děčín', 'Karlovy Vary', 'Chomutov',
        'Přerov', 'Jablonec nad Nisou', 'Prostějov', 'Mladá Boleslav',
        'Třebíč', 'Nový Jičín', 'Česká Lípa', 'Znojmo', 'Vsetín', 'Šumperk',
        'Kolín', 'Trutnov', 'Tábor', 'Litoměřice', 'Cheb', 'Kroměříž',
    ],
    'česká republika': [
        'Prague', 'Brno', 'Ostrava', 'Plzeň', 'Liberec', 'Olomouc',
        'Ústí nad Labem', 'České Budějovice', 'Hradec Králové', 'Pardubice',
        'Zlín', 'Havířov', 'Kladno', 'Most', 'Opava', 'Frýdek-Místek',
        'Karviná', 'Jihlava', 'Teplice', 'Děčín', 'Karlovy Vary', 'Chomutov',
        'Přerov', 'Jablonec nad Nisou', 'Prostějov', 'Mladá Boleslav',
        'Třebíč', 'Nový Jičín', 'Česká Lípa', 'Znojmo', 'Vsetín', 'Šumperk',
        'Kolín', 'Trutnov', 'Tábor', 'Litoměřice', 'Cheb', 'Kroměříž',
    ],

    # Estonia
    'estonia': [
        'Tallinn', 'Tartu', 'Narva', 'Pärnu', 'Kohtla-Järve', 'Viljandi',
        'Rakvere', 'Sillamäe', 'Maardu', 'Võru', 'Kuressaare', 'Valga', 'Jõhvi',
    ],
    'eesti': [
        'Tallinn', 'Tartu', 'Narva', 'Pärnu', 'Kohtla-Järve', 'Viljandi',
        'Rakvere', 'Sillamäe', 'Maardu', 'Võru', 'Kuressaare', 'Valga', 'Jõhvi',
    ],

    # Poland
    'poland': [
        'Warsaw', 'Kraków', 'Łódź', 'Wrocław', 'Poznań', 'Gdańsk', 'Szczecin',
        'Bydgoszcz', 'Lublin', 'Białystok', 'Katowice', 'Gdynia', 'Częstochowa',
        'Radom', 'Sosnowiec', 'Toruń', 'Kielce', 'Rzeszów', 'Gliwice', 'Zabrze',
        'Olsztyn', 'Bielsko-Biała', 'Bytom', 'Zielona Góra', 'Rybnik',
        'Ruda Śląska', 'Opole', 'Tychy', 'Gorzów Wielkopolski', 'Elbląg',
        'Dąbrowa Górnicza', 'Płock', 'Wałbrzych', 'Włocławek', 'Tarnów',
        'Chorzów', 'Koszalin', 'Kalisz', 'Legnica', 'Grudziądz', 'Jaworzno',
        'Słupsk', 'Jastrzębie-Zdrój', 'Nowy Sącz', 'Jelenia Góra', 'Siedlce',
        'Mysłowice', 'Konin',
    ],
    'polska': [
        'Warsaw', 'Kraków', 'Łódź', 'Wrocław', 'Poznań', 'Gdańsk', 'Szczecin',
        'Bydgoszcz', 'Lublin', 'Białystok', 'Katowice', 'Gdynia', 'Częstochowa',
        'Radom', 'Sosnowiec', 'Toruń', 'Kielce', 'Rzeszów', 'Gliwice', 'Zabrze',
        'Olsztyn', 'Bielsko-Biała', 'Bytom', 'Zielona Góra', 'Rybnik',
        'Ruda Śląska', 'Opole', 'Tychy', 'Gorzów Wielkopolski', 'Elbląg',
        'Dąbrowa Górnicza', 'Płock', 'Wałbrzych', 'Włocławek', 'Tarnów',
        'Chorzów', 'Koszalin', 'Kalisz', 'Legnica', 'Grudziądz', 'Jaworzno',
        'Słupsk', 'Jastrzębie-Zdrój', 'Nowy Sącz', 'Jelenia Góra', 'Siedlce',
        'Mysłowice', 'Konin',
    ],

    # Ukraine
    'ukraine': [
        'Kyiv', 'Lviv', 'Kharkiv', 'Odessa', 'Dnipro', 'Zaporizhzhia',
        'Vinnytsia', 'Mykolaiv', 'Poltava', 'Chernivtsi', 'Cherkasy',
        'Zhytomyr', 'Sumy', 'Ivano-Frankivsk', 'Ternopil', 'Lutsk', 'Rivne',
        'Khmelnytskyi', 'Uzhhorod', 'Kremenchuk', 'Kropyvnytskyi',
    ],
    'україна': [
        'Kyiv', 'Lviv', 'Kharkiv', 'Odessa', 'Dnipro', 'Zaporizhzhia',
        'Vinnytsia', 'Mykolaiv', 'Poltava', 'Chernivtsi', 'Cherkasy',
        'Zhytomyr', 'Sumy', 'Ivano-Frankivsk', 'Ternopil', 'Lutsk', 'Rivne',
        'Khmelnytskyi', 'Uzhhorod', 'Kremenchuk', 'Kropyvnytskyi',
    ],

    # Portugal
    'portugal': [
        'Lisbon', 'Porto', 'Amadora', 'Braga', 'Setúbal', 'Coimbra', 'Funchal',
        'Almada', 'Agualva-Cacém', 'Queluz', 'Vila Nova de Gaia', 'Aveiro',
        'Évora', 'Faro', 'Viseu', 'Leiria', 'Guimarães', 'Cascais', 'Oeiras',
        'Loures', 'Sintra', 'Barcelos', 'Viana do Castelo', 'Covilhã', 'Portimão',
        'Matosinhos', 'Gondomar', 'Maia', 'Vila Franca de Xira', 'Barreiro',
    ],

    # Romania
    'romania': [
        'Bucharest', 'Cluj-Napoca', 'Timișoara', 'Iași', 'Constanța', 'Craiova',
        'Brașov', 'Galați', 'Ploiești', 'Oradea', 'Brăila', 'Arad', 'Pitești',
        'Sibiu', 'Bacău', 'Târgu Mureș', 'Baia Mare', 'Buzău', 'Botoșani',
        'Satu Mare', 'Râmnicu Vâlcea', 'Drobeta-Turnu Severin', 'Suceava',
        'Piatra Neamț', 'Deva', 'Focșani', 'Alba Iulia', 'Bistrița', 'Tulcea',
        'Reșița', 'Câmpina',
    ],
    'românia': [
        'Bucharest', 'Cluj-Napoca', 'Timișoara', 'Iași', 'Constanța', 'Craiova',
        'Brașov', 'Galați', 'Ploiești', 'Oradea', 'Brăila', 'Arad', 'Pitești',
        'Sibiu', 'Bacău', 'Târgu Mureș', 'Baia Mare', 'Buzău', 'Botoșani',
        'Satu Mare', 'Râmnicu Vâlcea', 'Drobeta-Turnu Severin', 'Suceava',
        'Piatra Neamț', 'Deva', 'Focșani', 'Alba Iulia', 'Bistrița', 'Tulcea',
        'Reșița', 'Câmpina',
    ],

    # Latvia
    'latvia': [
        'Riga', 'Daugavpils', 'Liepāja', 'Jelgava', 'Jūrmala', 'Ventspils',
        'Rēzekne', 'Valmiera', 'Ogre', 'Tukums', 'Salaspils',
    ],
    'latvija': [
        'Riga', 'Daugavpils', 'Liepāja', 'Jelgava', 'Jūrmala', 'Ventspils',
        'Rēzekne', 'Valmiera', 'Ogre', 'Tukums', 'Salaspils',
    ],

    # Lithuania
    'lithuania': [
        'Vilnius', 'Kaunas', 'Klaipėda', 'Šiauliai', 'Panevėžys', 'Alytus',
        'Marijampolė', 'Mažeikiai', 'Jonava', 'Utena', 'Kėdainiai', 'Telšiai',
        'Ukmergė', 'Visaginas',
    ],
    'lietuva': [
        'Vilnius', 'Kaunas', 'Klaipėda', 'Šiauliai', 'Panevėžys', 'Alytus',
        'Marijampolė', 'Mažeikiai', 'Jonava', 'Utena', 'Kėdainiai', 'Telšiai',
        'Ukmergė', 'Visaginas',
    ],

    # Hungary
    'hungary': [
        'Budapest', 'Debrecen', 'Miskolc', 'Pécs', 'Győr', 'Nyíregyháza',
        'Kecskemét', 'Székesfehérvár', 'Szombathely', 'Szolnok', 'Tatabánya',
        'Kaposvár', 'Érd', 'Veszprém', 'Eger', 'Sopron', 'Zalaegerszeg',
        'Szeged', 'Ózd', 'Hódmezővásárhely', 'Dunaújváros', 'Mosonmagyaróvár',
    ],
    'magyarország': [
        'Budapest', 'Debrecen', 'Miskolc', 'Pécs', 'Győr', 'Nyíregyháza',
        'Kecskemét', 'Székesfehérvár', 'Szombathely', 'Szolnok', 'Tatabánya',
        'Kaposvár', 'Érd', 'Veszprém', 'Eger', 'Sopron', 'Zalaegerszeg',
        'Szeged', 'Ózd', 'Hódmezővásárhely', 'Dunaújváros', 'Mosonmagyaróvár',
    ],

    # Slovakia
    'slovakia': [
        'Bratislava', 'Košice', 'Prešov', 'Žilina', 'Nitra', 'Banská Bystrica',
        'Trnava', 'Martin', 'Trenčín', 'Poprad', 'Prievidza', 'Považská Bystrica',
        'Zvolen', 'Michalovce', 'Nové Zámky', 'Spišská Nová Ves', 'Komárno',
        'Levice', 'Liptovský Mikuláš', 'Humenné', 'Bardejov', 'Rimavská Sobota',
    ],
    'slovensko': [
        'Bratislava', 'Košice', 'Prešov', 'Žilina', 'Nitra', 'Banská Bystrica',
        'Trnava', 'Martin', 'Trenčín', 'Poprad', 'Prievidza', 'Považská Bystrica',
        'Zvolen', 'Michalovce', 'Nové Zámky', 'Spišská Nová Ves', 'Komárno',
        'Levice', 'Liptovský Mikuláš', 'Humenné', 'Bardejov', 'Rimavská Sobota',
    ],

    # Germany
    'germany': [
        'Berlin', 'Hamburg', 'Munich', 'Cologne', 'Frankfurt', 'Stuttgart',
        'Düsseldorf', 'Leipzig', 'Dortmund', 'Essen', 'Bremen', 'Dresden',
        'Hanover', 'Nuremberg', 'Duisburg', 'Bochum', 'Wuppertal', 'Bielefeld',
        'Bonn', 'Münster', 'Karlsruhe', 'Mannheim', 'Augsburg', 'Wiesbaden',
        'Gelsenkirchen', 'Mönchengladbach', 'Braunschweig', 'Kiel', 'Chemnitz',
        'Aachen', 'Halle', 'Magdeburg', 'Freiburg', 'Krefeld', 'Lübeck',
        'Mainz', 'Erfurt', 'Rostock',
    ],
    'deutschland': [
        'Berlin', 'Hamburg', 'Munich', 'Cologne', 'Frankfurt', 'Stuttgart',
        'Düsseldorf', 'Leipzig', 'Dortmund', 'Essen', 'Bremen', 'Dresden',
        'Hanover', 'Nuremberg', 'Duisburg', 'Bochum', 'Wuppertal', 'Bielefeld',
        'Bonn', 'Münster', 'Karlsruhe', 'Mannheim', 'Augsburg', 'Wiesbaden',
        'Gelsenkirchen', 'Mönchengladbach', 'Braunschweig', 'Kiel', 'Chemnitz',
        'Aachen', 'Halle', 'Magdeburg', 'Freiburg', 'Krefeld', 'Lübeck',
        'Mainz', 'Erfurt', 'Rostock',
    ],

    # Austria
    'austria': [
        'Vienna', 'Graz', 'Linz', 'Salzburg', 'Innsbruck', 'Klagenfurt',
        'Villach', 'Wels', 'St. Pölten', 'Dornbirn', 'Wiener Neustadt',
        'Steyr', 'Feldkirch', 'Bregenz', 'Leonding',
    ],
    'österreich': [
        'Vienna', 'Graz', 'Linz', 'Salzburg', 'Innsbruck', 'Klagenfurt',
        'Villach', 'Wels', 'St. Pölten', 'Dornbirn', 'Wiener Neustadt',
        'Steyr', 'Feldkirch', 'Bregenz', 'Leonding',
    ],

    # Finland
    'finland': [
        'Helsinki', 'Espoo', 'Tampere', 'Vantaa', 'Oulu', 'Turku',
        'Jyväskylä', 'Lahti', 'Kuopio', 'Pori', 'Kouvola', 'Joensuu',
        'Lappeenranta', 'Hämeenlinna', 'Vaasa', 'Rovaniemi', 'Seinäjoki',
        'Mikkeli', 'Kotka', 'Porvoo',
    ],
    'suomi': [
        'Helsinki', 'Espoo', 'Tampere', 'Vantaa', 'Oulu', 'Turku',
        'Jyväskylä', 'Lahti', 'Kuopio', 'Pori', 'Kouvola', 'Joensuu',
        'Lappeenranta', 'Hämeenlinna', 'Vaasa', 'Rovaniemi', 'Seinäjoki',
        'Mikkeli', 'Kotka', 'Porvoo',
    ],

    # Norway
    'norway': [
        'Oslo', 'Bergen', 'Trondheim', 'Stavanger', 'Drammen', 'Fredrikstad',
        'Kristiansand', 'Sandnes', 'Tromsø', 'Sarpsborg', 'Skien', 'Ålesund',
        'Sandefjord', 'Haugesund', 'Tønsberg', 'Moss', 'Porsgrunn', 'Bodø',
        'Arendal',
    ],
    'norge': [
        'Oslo', 'Bergen', 'Trondheim', 'Stavanger', 'Drammen', 'Fredrikstad',
        'Kristiansand', 'Sandnes', 'Tromsø', 'Sarpsborg', 'Skien', 'Ålesund',
        'Sandefjord', 'Haugesund', 'Tønsberg', 'Moss', 'Porsgrunn', 'Bodø',
        'Arendal',
    ],

    # Sweden
    'sweden': [
        'Stockholm', 'Gothenburg', 'Malmö', 'Uppsala', 'Västerås', 'Örebro',
        'Linköping', 'Helsingborg', 'Jönköping', 'Norrköping', 'Lund', 'Umeå',
        'Gävle', 'Borås', 'Södertälje', 'Eskilstuna', 'Halmstad', 'Växjö',
        'Karlstad', 'Sundsvall',
    ],
    'sverige': [
        'Stockholm', 'Gothenburg', 'Malmö', 'Uppsala', 'Västerås', 'Örebro',
        'Linköping', 'Helsingborg', 'Jönköping', 'Norrköping', 'Lund', 'Umeå',
        'Gävle', 'Borås', 'Södertälje', 'Eskilstuna', 'Halmstad', 'Växjö',
        'Karlstad', 'Sundsvall',
    ],

    # Denmark
    'denmark': [
        'Copenhagen', 'Aarhus', 'Odense', 'Aalborg', 'Esbjerg', 'Randers',
        'Kolding', 'Horsens', 'Vejle', 'Roskilde', 'Helsingør', 'Silkeborg',
        'Næstved', 'Fredericia', 'Viborg',
    ],
    'danmark': [
        'Copenhagen', 'Aarhus', 'Odense', 'Aalborg', 'Esbjerg', 'Randers',
        'Kolding', 'Horsens', 'Vejle', 'Roskilde', 'Helsingør', 'Silkeborg',
        'Næstved', 'Fredericia', 'Viborg',
    ],

    # Greece
    'greece': [
        'Athens', 'Thessaloniki', 'Patras', 'Piraeus', 'Larissa', 'Heraklion',
        'Peristeri', 'Kallithea', 'Acharnes', 'Kalamaria', 'Nikaia', 'Glyfada',
        'Rhodes', 'Volos', 'Ioannina', 'Chalandri', 'Nea Ionia', 'Ilioupoli',
        'Keratsini',
    ],
    'ελλάδα': [
        'Athens', 'Thessaloniki', 'Patras', 'Piraeus', 'Larissa', 'Heraklion',
        'Peristeri', 'Kallithea', 'Acharnes', 'Kalamaria', 'Nikaia', 'Glyfada',
        'Rhodes', 'Volos', 'Ioannina', 'Chalandri', 'Nea Ionia', 'Ilioupoli',
        'Keratsini',
    ],

    # Israel
    'israel': [
        'Tel Aviv', 'Jerusalem', 'Haifa', 'Rishon LeZion', 'Petah Tikva',
        'Ashdod', 'Netanya', 'Beer Sheva', 'Bnei Brak', 'Holon', 'Ramat Gan',
        'Ashkelon', 'Rehovot', 'Bat Yam', 'Herzliya', 'Kfar Saba', "Ra'anana",
        'Nazareth', 'Modiin',
    ],

    # Serbia
    'serbia': [
        'Belgrade', 'Novi Sad', 'Niš', 'Kragujevac', 'Subotica', 'Zrenjanin',
        'Pančevo', 'Čačak', 'Novi Pazar', 'Kruševac', 'Vranje', 'Šabac',
        'Jagodina', 'Smederevo', 'Valjevo',
    ],
    'srbija': [
        'Belgrade', 'Novi Sad', 'Niš', 'Kragujevac', 'Subotica', 'Zrenjanin',
        'Pančevo', 'Čačak', 'Novi Pazar', 'Kruševac', 'Vranje', 'Šabac',
        'Jagodina', 'Smederevo', 'Valjevo',
    ],

    # Croatia
    'croatia': [
        'Zagreb', 'Split', 'Rijeka', 'Osijek', 'Zadar', 'Pula',
        'Slavonski Brod', 'Karlovac', 'Varaždin', 'Šibenik', 'Sisak', 'Vukovar',
    ],
    'hrvatska': [
        'Zagreb', 'Split', 'Rijeka', 'Osijek', 'Zadar', 'Pula',
        'Slavonski Brod', 'Karlovac', 'Varaždin', 'Šibenik', 'Sisak', 'Vukovar',
    ],

    # Bulgaria
    'bulgaria': [
        'Sofia', 'Plovdiv', 'Varna', 'Burgas', 'Ruse', 'Stara Zagora',
        'Pleven', 'Sliven', 'Dobrich', 'Shumen', 'Pernik', 'Haskovo',
        'Yambol', 'Pazardzhik',
    ],
    'българия': [
        'Sofia', 'Plovdiv', 'Varna', 'Burgas', 'Ruse', 'Stara Zagora',
        'Pleven', 'Sliven', 'Dobrich', 'Shumen', 'Pernik', 'Haskovo',
        'Yambol', 'Pazardzhik',
    ],
}


def _get_sub_queries(location: str, query_term: str) -> list[str]:
    """
    For large cities return one query per district.
    For small cities / single districts return a single query.
    """
    key = location.strip().lower().split(',')[0].strip()
    districts = CITY_DISTRICTS.get(key)
    if districts:
        return [f'{query_term} in {d}' for d in districts]
    return [f'{query_term} in {location}']


def _get_location_queries(location: str, query_term: str) -> list[str]:
    """
    If location matches a known country, return one query per major city.
    Otherwise fall back to district-level splitting for large cities,
    or a single query for everything else.
    """
    key = location.strip().lower().split(',')[0].strip()
    cities = COUNTRY_CITIES.get(key)
    if cities:
        return [f'{query_term} in {city}' for city in cities]
    return _get_sub_queries(location, query_term)


# Fields to request from Outscraper (no fields filter = get everything)
OUTSCRAPER_FIELDS = (
    'name,type,subtypes,address,full_address,city,country_code,latitude,longitude,'
    'phone,website,rating,reviews,range,working_hours,'
    'permanently_closed,temporarily_closed,'
    'order_links,booking_appointment_link,reservation_links,photos,photo,url,place_id'
)

# ── Delivery platform matchers ────────────────────────────────────────────────
# Each entry: (column_key, display_name, [domain_fragments])
_DELIVERY_MATCHERS = [
    ('delivery_wolt',       'Wolt',        ['wolt.com']),
    ('delivery_bolt_food',  'Bolt Food',   ['food.bolt.eu', 'bolt.eu/food', 'bolt.eu']),
    ('delivery_uber_eats',  'Uber Eats',   ['ubereats.com']),
    ('delivery_foodora',    'Foodora',     ['foodora.com', 'foodora.cz', 'foodora.at',
                                            'foodora.se', 'foodora.no', 'foodora.fi']),
    ('delivery_deliveroo',  'Deliveroo',   ['deliveroo.com']),
    ('delivery_just_eat',   'Just Eat',    ['just-eat.com', 'just-eat.co.uk', 'justeat.com']),
    ('delivery_doordash',   'DoorDash',    ['doordash.com']),
    ('delivery_glovo',      'Glovo',       ['glovoapp.com', 'glovo.com']),
    ('delivery_takeaway',   'Takeaway',    ['takeaway.com', 'lieferando.de', 'thuisbezorgd.nl',
                                            'pyszne.pl', 'pizza.cz', 'damejidlo.cz']),
]

# ── Reservation / booking platform matchers ───────────────────────────────────
_RESERVATION_MATCHERS = [
    ('reservation_opentable',   'OpenTable',      ['opentable.com']),
    ('reservation_resy',        'Resy',            ['resy.com']),
    ('reservation_sevenrooms',  'SevenRooms',      ['sevenrooms.com']),
    ('reservation_tock',        'Tock',            ['tock.com', 'exploretock.com']),
    ('reservation_quandoo',     'Quandoo',         ['quandoo.com', 'quandoo.cz', 'quandoo.de',
                                                    'quandoo.co.uk']),
    ('reservation_thefork',     'TheFork',         ['thefork.com', 'lafourchette.com',
                                                    'eltenedor.com', 'dimmi.com.au']),
    ('reservation_bookatable',  'Bookatable',      ['bookatable.com', 'bookatable.co.uk']),
    ('reservation_resdiary',    'ResDiary',        ['resdiary.com']),
    ('reservation_apetee',      'Apetee',          ['apetee.com']),
    ('reservation_dishco',      'Dish.co',         ['dish.co', 'dish.com']),
    ('reservation_forky',       'Forky',           ['forky.cz']),
    ('reservation_google',      'Google Reserve',  ['google.com/maps/reserve',
                                                    'google.com/maps/contrib',
                                                    'maps.google']),
]


def _extract_company_name(url: str, matchers: list) -> str:
    """Return the display name of the first matcher that matches the URL."""
    url_lower = url.lower()
    for _, name, domains in matchers:
        if any(d in url_lower for d in domains):
            return name
    return ''


def _to_list(val) -> list:
    if not val:
        return []
    if isinstance(val, list):
        return [str(v) for v in val if v]
    return [str(val)]


def _parse_place(r: dict, business_type: str) -> dict:
    order_links   = _to_list(r.get('order_links'))
    # Use booking_appointment_link + reservation_links for broadest coverage
    booking_links = list(dict.fromkeys(
        _to_list(r.get('booking_appointment_link')) +
        _to_list(r.get('reservation_links'))
    ))
    # Clean Google redirect wrappers from reservation_links
    cleaned_booking = []
    for link in booking_links:
        if link.startswith('/url?q='):
            # Extract the real URL from Google's redirect
            import urllib.parse
            qs = urllib.parse.parse_qs(link[5:])  # strip /url?
            real = qs.get('q', [link])[0]
            cleaned_booking.append(real)
        else:
            cleaned_booking.append(link)
    booking_links = list(dict.fromkeys(cleaned_booking))

    result = {}

    # ── Per-platform delivery columns ─────────────────────────────────────────
    matched_delivery_urls = set()
    delivery_company_names = []
    for col, name, domains in _DELIVERY_MATCHERS:
        found = ''
        for link in order_links:
            if any(d in link.lower() for d in domains):
                found = link
                matched_delivery_urls.add(link)
                delivery_company_names.append(name)
                break
        result[col] = found

    other_delivery = [l for l in order_links if l not in matched_delivery_urls]
    result['delivery_other'] = other_delivery[0] if other_delivery else ''
    if other_delivery:
        delivery_company_names.append('Other')

    result['delivery_companies'] = ', '.join(delivery_company_names)
    result['has_delivery'] = 'TRUE' if delivery_company_names else ''

    # ── Per-platform reservation columns ──────────────────────────────────────
    matched_res_urls = set()
    reservation_company_names = []
    for col, name, domains in _RESERVATION_MATCHERS:
        found = ''
        for link in booking_links:
            if any(d in link.lower() for d in domains):
                found = link
                matched_res_urls.add(link)
                reservation_company_names.append(name)
                break
        result[col] = found

    other_res = [l for l in booking_links if l not in matched_res_urls]
    # Filter out restaurant's own website from "other" if we have their website
    own_site = (r.get('website') or '').lower().rstrip('/')
    if own_site:
        other_res = [l for l in other_res if own_site not in l.lower()]
    result['reservation_other'] = other_res[0] if other_res else ''
    if other_res:
        reservation_company_names.append('Direct')
    elif booking_links and not reservation_company_names:
        # Has booking links but none matched — mark as Direct
        reservation_company_names.append('Direct')

    result['reservation_companies'] = ', '.join(reservation_company_names)
    result['has_reservation'] = 'TRUE' if (booking_links or reservation_company_names) else ''

    # ── Working hours ──────────────────────────────────────────────────────────
    wh = r.get('working_hours', '')
    if isinstance(wh, dict):
        wh = '; '.join(f"{k}: {', '.join(v) if isinstance(v, list) else v}" for k, v in wh.items())
    elif isinstance(wh, list):
        wh = '; '.join(str(h) for h in wh)

    # ── First photo URL ────────────────────────────────────────────────────────
    photos = _to_list(r.get('photos'))
    photo1 = photos[0] if photos else r.get('photo', '')

    result.update({
        'name':                r.get('name', ''),
        'business_type':       business_type,
        'category':            r.get('subtypes', '') or r.get('type', ''),
        'address':             r.get('full_address', '') or r.get('address', ''),
        'city':                r.get('city', ''),
        'country':             r.get('country_code', '') or r.get('country', ''),
        'latitude':            str(r.get('latitude', '')),
        'longitude':           str(r.get('longitude', '')),
        'phone':               r.get('phone', ''),
        'website':             r.get('website', ''),   # FIXED: was 'site'
        'rating':              str(r.get('rating', '')),
        'reviews':             str(r.get('reviews', '')),
        'price_range':         r.get('range', ''),
        'working_hours':       wh,
        'permanently_closed':  'Yes' if r.get('permanently_closed') else '',
        'temporarily_closed':  'Yes' if r.get('temporarily_closed') else '',
        'photo_url_1':         photo1,
        'google_maps_url':     r.get('url', ''),
        'place_id':            r.get('place_id', ''),
        # kept for app.py compatibility
        'platform_url':        r.get('url', ''),
        'brand_name':          '',
    })
    return result


def scrape_google_maps(
    location: str,
    cuisine: str,
    job: dict,
    business_types: list = None,
    min_reviews: int = 0,
    min_rating: float = 0.0,
    require_website: bool = False,
    require_phone: bool = False,
) -> list[dict]:
    """
    Query Outscraper for each business type, dedup by place_id, apply filters.
    Returns list of records with per-platform delivery/reservation columns.
    """
    api_key = os.environ.get('OUTSCRAPER_API_KEY')
    if not api_key:
        raise ValueError(
            'OUTSCRAPER_API_KEY is not set — add it to Render environment variables.'
        )

    types_to_scrape = business_types or DEFAULT_BUSINESS_TYPES
    client = ApiClient(api_key=api_key)

    all_records: dict[str, dict] = {}   # place_id → record
    total_types = len(types_to_scrape)

    for idx, btype in enumerate(types_to_scrape, 1):
        query_term = BUSINESS_TYPE_QUERIES.get(btype, btype)
        sub_queries = _get_location_queries(location, query_term)
        total_sub = len(sub_queries)
        is_district_mode = total_sub > 1

        print(f'[Google Maps] {btype}: {total_sub} sub-queries for "{location}"')

        for q_idx, query in enumerate(sub_queries, 1):
            pct_base  = int((idx - 1) / total_types * 85)
            pct_inner = int((q_idx - 1) / total_sub / total_types * 85)
            job['progress'] = max(5, pct_base + pct_inner)

            if is_district_mode:
                city_name = query.split(' in ', 1)[-1]
                job['message'] = (
                    f'{query_term.capitalize()}: {city_name} ({q_idx}/{total_sub})'
                    f' — {len(all_records)} found so far'
                )
            else:
                job['message'] = f'Fetching {query_term} from Google Maps... (~30s)'

            print(f'[Google Maps] Query: {query}')

            try:
                raw = client.google_maps_search(
                    [query],
                    language='en',
                    limit=500,
                    drop_duplicates=True,
                    fields=OUTSCRAPER_FIELDS,
                )
                # API returns flat list of dicts (not list-of-lists)
                places = raw if isinstance(raw, list) and raw and isinstance(raw[0], dict) else (raw[0] if raw else [])
                print(f'[Google Maps] {query}: {len(places)} raw results')

                added = 0
                for place in places:
                    pid = place.get('place_id', '')
                    if not pid:
                        continue
                    if pid not in all_records:
                        all_records[pid] = _parse_place(place, query_term)
                        added += 1
                    else:
                        existing = all_records[pid]['business_type']
                        if query_term not in existing:
                            all_records[pid]['business_type'] = f'{existing}, {query_term}'

                job['scraped'] = len(all_records)
                print(f'[Google Maps] +{added} new (total {len(all_records)})')

            except Exception as e:
                print(f'[Google Maps] query failed: {query} — {e}')

    results = list(all_records.values())

    # Apply filters
    if min_reviews > 0:
        results = [r for r in results if int(r.get('reviews') or 0) >= min_reviews]
    if min_rating > 0:
        results = [r for r in results if float(r.get('rating') or 0) >= min_rating]
    if require_website:
        results = [r for r in results if r.get('website')]
    if require_phone:
        results = [r for r in results if r.get('phone')]

    # Compute stats for the job
    job['gm_stats'] = {
        'total':            len(results),
        'with_phone':       sum(1 for r in results if r.get('phone')),
        'with_website':     sum(1 for r in results if r.get('website')),
        'with_delivery':    sum(1 for r in results if r.get('has_delivery') == 'TRUE'),
        'with_reservation': sum(1 for r in results if r.get('has_reservation') == 'TRUE'),
    }

    job['scraped']  = len(results)
    job['progress'] = 100
    job['message']  = f'Google Maps: found {len(results)} places in {location}.'
    print(f'[Google Maps] Done — {len(results)} results after dedup + filters')
    return results
