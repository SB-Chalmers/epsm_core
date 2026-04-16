"""Weather file selection: nearest EPW station from 293 OneBuilding Sweden stations."""
from __future__ import annotations

import math
import re
from pathlib import Path

_EPW_DIR = Path(__file__).resolve().parent.parent.parent / "epw"

# Default TMY period – latest available, best for current EPC comparison.
DEFAULT_PERIOD = "2011-2025"

# ── 293 stations ────────────────────────────────────────────────────────
# (wmo, lat, lon, region_code, station_name)
# Coordinates extracted from EPW LOCATION headers.
_STATIONS: list[tuple[str, float, float, str, str]] = [
    ("020001",  56.08300,  13.21300, "SN", "Ljungbyhed.AP"),
    ("020130",  67.72690,  17.47110, "NB", "Ritsem"),
    ("020200",  68.42030,  18.16810, "NB", "Riksgransen-Katterjakk.Stn"),
    ("020230",  68.43300,  18.63300, "NB", "Tornehamn"),
    ("020240",  67.49640,  18.29440, "NB", "Stora.Sjofallet"),
    ("020290",  67.91140,  18.60720, "NB", "Tarfala"),
    ("020310",  68.07470,  19.83950, "NB", "Rensjon"),
    ("020320",  68.21700,  19.71700, "NB", "Tornetrask.Lake"),
    ("020360",  67.85420,  19.02560, "NB", "Nikkaluokta"),
    ("020380",  67.25640,  20.27470, "NB", "Ladnivare"),
    ("020430",  67.93300,  21.06700, "NB", "Esrange"),
    ("020440",  67.82280,  20.34000, "NB", "Kiruna.AP"),
    ("020450",  67.84060,  20.41050, "NB", "Kiruna-Swedish.Institute.Space.Physics"),
    ("020490",  67.13200,  20.81500, "NB", "Gallivare-Lapland-Malmberget"),
    ("020520",  66.94180,  17.73890, "NB", "Kvikkjokk.Heliport"),
    ("020540",  68.04390,  21.75500, "NB", "Nedre.Soppero"),
    ("020550",  68.66690,  21.53850, "NB", "Naimakka"),
    ("020640",  67.33780,  22.23360, "NB", "Saittarova"),
    ("020720",  67.73170,  22.82700, "NB", "Parkalompolo"),
    ("020740",  59.26700,  15.33300, "OR", "Orebro-Eekeby"),
    ("020810",  68.44190,  22.44360, "NB", "Karesuando"),
    ("020840",  68.05000,  22.00000, "NB", "Lannavaara"),
    ("020860",  67.76100,  22.35200, "NB", "Lainio"),
    ("020880",  67.08670,  22.21910, "NB", "Kompelusvaara"),
    ("020920",  67.95000,  23.46700, "NB", "Muodoslompolo"),
    ("020950",  67.20360,  23.39000, "NB", "Pajala"),
    ("020990",  55.43300,  13.83300, "SN", "Ystad"),
    ("021010",  65.80610,  15.08280, "VB", "Hemavan.Tarnaby.AP"),
    ("021020",  65.09440,  14.50860, "VB", "Stekenjokk"),
    ("021030",  65.78000,  15.06440, "VB", "Hemavan.Gierevarto"),
    ("021050",  65.54200,  14.98600, "VB", "Abelvattnet.Hydro.Power.Plant"),
    ("021080",  65.06700,  14.80000, "VB", "Klimpen-Klimpfjall"),
    ("021100",  65.32810,  15.06890, "VB", "Gielas"),
    ("021160",  63.31700,  13.65000, "JA", "Morsil"),
    ("021180",  65.31700,  16.03300, "VB", "Dikanas-Skansnas"),
    ("021190",  66.88720,  18.01970, "NB", "Kvikkjokk.Arrenjarka"),
    ("021210",  66.68170,  16.10890, "NB", "Merkenes"),
    ("021230",  66.32420,  17.09440, "NB", "Jakkvik"),
    ("021240",  66.05140,  17.83970, "NB", "Arjeplog"),
    ("021260",  65.00950,  17.69940, "VB", "Gunnarn"),
    ("021270",  65.06700,  17.16700, "VB", "Stensele"),
    ("021290",  64.96700,  17.70000, "VB", "Gunnarn-Storuman.AP"),
    ("021300",  66.48610,  16.41720, "NB", "Roparudden"),
    ("021350",  65.55880,  17.85600, "VB", "Buresjon"),
    ("021380",  60.50000,  18.86700, "UP", "Grundkallen.Lighthouse"),
    ("021410",  66.30000,  19.20000, "NB", "Tjakaape"),
    ("021440",  65.98300,  18.93300, "NB", "Lake.Abraur"),
    ("021460",  66.50500,  19.67500, "NB", "Vajmat"),
    ("021470",  65.15220,  18.59750, "VB", "Mala-Brannan"),
    ("021490",  65.59530,  19.26830, "NB", "Arvidsjaur.AP"),
    ("021510",  66.48330,  20.16670, "NB", "Jokkmokk.AP"),
    ("021520",  66.30000,  20.41700, "NB", "Sudok"),
    ("021540",  65.86780,  20.15420, "NB", "Vidsels.AP"),
    ("021560",  63.96700,  13.71700, "JA", "Stensjon"),
    ("021590",  65.12000,  20.77000, "VB", "Fallfors.AP"),
    ("021610",  66.75310,  20.92830, "NB", "Nattavaara"),
    ("021620",  56.46700,  13.65000, "KR", "Markaryd"),
    ("021640",  66.38300,  21.63300, "NB", "Palkem"),
    ("021700",  65.75280,  21.76500, "NB", "Savast"),
    ("021710",  65.80830,  21.63450, "NB", "Boden"),
    ("021730",  65.67030,  21.06640, "NB", "Alvsbyn"),
    ("021740",  66.28030,  21.13310, "NB", "Lakatrask"),
    ("021760",  65.03520,  21.55750, "VB", "Pite-Ronnskar.Lighthouse"),
    ("021810",  66.26300,  22.84750, "NB", "Overkalix-Svartbyn"),
    ("021840",  66.81060,  22.33640, "NB", "Paharova"),
    ("021860",  65.54440,  22.12810, "NB", "Lulea.AP"),
    ("021880",  65.31440,  22.36980, "NB", "Rodkallen.Lighthouse"),
    ("021910",  65.72980,  23.08740, "NB", "Kalix-Storon"),
    ("021970",  65.82360,  24.11140, "NB", "Haparanda"),
    ("021990",  66.62360,  23.46810, "NB", "Ylinenjarvi"),
    ("022000",  63.98300,  12.86700, "JA", "Edevik"),
    ("022070",  63.28280,  12.12190, "JA", "Storlien-Visjovalen"),
    ("022090",  63.04470,  12.27780, "JA", "Sylarna"),
    ("022100",  63.18640,  12.17610, "JA", "Blahammaren"),
    ("022160",  63.30550,  13.87670, "JA", "Mattmar"),
    ("022170",  63.37360,  13.16060, "JA", "Are"),
    ("022190",  64.50440,  14.22080, "JA", "Gaddede"),
    ("022210",  63.83970,  13.50390, "JA", "Korsvattnet"),
    ("022260",  63.19560,  14.50030, "JA", "Are.Ostersund.AP"),
    ("022300",  64.21830,  15.55640, "JA", "Gubbhogen"),
    ("022310",  63.67720,  14.60810, "JA", "Follinge"),
    ("022320",  64.45000,  15.60000, "JA", "Norraker"),
    ("022330",  64.96780,  15.37920, "VB", "Saxnas"),
    ("022340",  63.86700,  15.58300, "JA", "Stromsund"),
    ("022360",  63.76940,  15.33110, "JA", "Hallhaxasen"),
    ("022420",  64.08930,  16.23550, "JA", "Hoting"),
    ("022430",  63.68390,  16.95000, "VN", "Junsele"),
    ("022450",  64.57930,  16.84210, "VB", "Vilhelmina-South.Lapland.AP"),
    ("022470",  63.15220,  16.17330, "JA", "Krangede"),
    ("022520",  64.45000,  17.08300, "VB", "Idvattnet"),
    ("022540",  64.16610,  17.31890, "VB", "Asele"),
    ("022560",  64.73440,  17.40330, "VB", "Ristrask"),
    ("022590",  63.04900,  17.76900, "VN", "Kramfors-Solleftea-High.Coast.AP"),
    ("022600",  63.12530,  18.25560, "VN", "Vastmarkum"),
    ("022610",  64.54950,  18.71690, "VB", "Lycksele.AP"),
    ("022620",  66.56700,  16.35000, "NB", "Vuoggatjalme"),
    ("022630",  64.07550,  18.36560, "VB", "Fredrika"),
    ("022650",  63.65140,  18.55030, "VN", "Hemling"),
    ("022670",  63.41170,  18.97970, "VN", "Ornskoldsvik.AP"),
    ("022690",  63.18860,  19.02060, "VN", "Skagsudde.Lighthouse"),
    ("022710",  64.92640,  19.37860, "VB", "Norsjo"),
    ("022760",  63.56700,  19.50000, "VB", "Nordmaling"),
    ("022820",  64.56620,  19.69740, "VB", "Petistrask"),
    ("022840",  63.43780,  19.68140, "VB", "Jarnasklubb"),
    ("022860",  63.80000,  20.28330, "VB", "Umea.AP"),
    ("022861",  61.26700,  17.10000, "GV", "Soderhamn-Helsinge.AP"),
    ("022870",  63.80690,  20.86440, "VB", "Holmon"),
    ("022880",  63.59400,  20.75200, "VB", "Holmogadd.Lighthouse"),
    ("022890",  63.33300,  20.18300, "VN", "Sydostbrotten.Lighthouse"),
    ("022920",  64.43580,  21.28000, "VB", "Hokmarksberget"),
    ("022930",  64.62470,  21.07700, "VB", "Skelleftea.AP"),
    ("022970",  64.48140,  21.57920, "VB", "Bjuroklubb.Lighthouse"),
    ("023020",  61.84000,  12.28720, "KO", "Storbo"),
    ("023030",  62.72920,  12.72640, "JA", "Flatruet"),
    ("023040",  61.86300,  12.22070, "KO", "Flotningen"),
    ("023060",  61.13300,  12.81700, "KO", "Rorbacksnas"),
    ("023070",  61.88950,  12.85440, "KO", "Idrefjall"),
    ("023080",  62.45030,  12.67030, "JA", "Tannas"),
    ("023100",  62.80000,  13.06700, "JA", "Storsjo.Kapell"),
    ("023110",  61.15810,  13.11390, "KO", "Hogfjallshotellet"),
    ("023160",  61.69215,  13.18810, "KO", "Sarna"),
    ("023170",  62.09440,  13.61170, "JA", "Dravagen"),
    ("023190",  62.75580,  13.84580, "JA", "Bortnan"),
    ("023210",  61.25440,  14.03860, "KO", "Alvdalen"),
    ("023250",  62.49610,  14.15720, "JA", "Klovsjohojden"),
    ("023270",  62.04610,  14.40690, "JA", "Harjedalen.Sveg.AP"),
    ("023290",  61.66110,  14.99300, "GV", "Hamra"),
    ("023310",  62.75140,  15.08780, "JA", "Hunge"),
    ("023340",  62.05250,  15.46360, "GV", "Finneby"),
    ("023370",  62.26310,  15.67080, "GV", "Norrhog"),
    ("023380",  61.36140,  15.71780, "GV", "Edsbyn"),
    ("023420",  62.51700,  16.18300, "VN", "Fransta"),
    ("023430",  62.49440,  16.27750, "VN", "Torpshammar"),
    ("023470",  61.82720,  16.54190, "GV", "Delsbo"),
    ("023490",  62.76280,  16.73920, "VN", "Sillre"),
    ("023540",  62.43060,  17.34470, "VN", "Rasta"),
    ("023550",  61.70300,  17.52100, "GV", "Kuggoren"),
    ("023610",  62.63300,  17.95000, "VN", "Harnosand"),
    ("023660",  62.52280,  17.44940, "VN", "Harnosand-Sundsvall.Timra.AP"),
    ("023670",  62.36800,  17.52140, "VN", "Spikarna-Alnon.Island"),
    ("023680",  62.22080,  17.74280, "VN", "Bramon.Lighthouse"),
    ("023820",  62.64220,  18.08880, "VN", "Lungo.Lighthouse"),
    ("024000",  60.35000,  12.65000, "VR", "Ostmark"),
    ("024020",  59.86700,  11.96700, "VR", "Skillingmark"),
    ("024030",  58.70130,  13.10930, "VG", "Naven.Lighthouse-Vanern.Lake"),
    ("024070",  60.67640,  13.70720, "KO", "Malung"),
    ("024080",  59.22200,  12.07810, "VG", "Blomskog"),
    ("024090",  59.05000,  12.70000, "VG", "Amal"),
    ("024110",  59.67470,  12.63810, "VR", "Arvika.AP"),
    ("024130",  60.75690,  12.77220, "VR", "Brattmon"),
    ("024170",  58.75000,  13.15000, "VG", "Palgrunden.Water.Quality.Monitoring.Stn-Vanern.Lak"),
    ("024180",  59.44470,  13.33750, "VR", "Karlstad.AP"),
    ("024190",  59.35920,  13.47190, "VR", "Karlstad"),
    ("024230",  59.86440,  13.11940, "VR", "Sunne-Holmby.AP"),
    ("024240",  59.95000,  14.95000, "OR", "Stalldalen"),
    ("024260",  60.15390,  13.80190, "VR", "Gustavsfors"),
    ("024280",  59.10000,  14.36700, "OR", "Atorp"),
    ("024285",  60.15800,  12.99100, "VR", "Torsby.AP"),
    ("024290",  59.66190,  14.18310, "VR", "Daglosen"),
    ("024310",  59.87030,  15.25220, "OR", "Kloten"),
    ("024320",  59.22890,  15.04560, "OR", "Orebro.AP"),
    ("024350",  60.42920,  15.50080, "KO", "Borlange-Dala.AP"),
    ("024400",  60.96220,  16.43110, "GV", "Amot"),
    ("024410",  60.96080,  14.50720, "KO", "Mora-Siljan.AP"),
    ("024430",  59.65000,  17.11670, "UP", "Enkoping"),
    ("024440",  60.16782,  16.31861, "KO", "Folkarna"),
    ("024460",  59.58900,  16.63400, "VM", "Stockholm.Vasteras.AP"),
    ("024490",  59.35070,  16.70680, "SD", "Eskilstuna.AP"),
    ("024500",  60.72960,  17.55780, "GV", "Eggegrund.Lighthouse"),
    ("024520",  59.29940,  14.89860, "OR", "Kilsbergen-Suttarboda"),
    ("024530",  60.59560,  16.95590, "GV", "Gavle"),
    ("024560",  60.23580,  17.90440, "UP", "Film"),
    ("024580",  59.90080,  17.59580, "UP", "Uppsala-Arna.AP"),
    ("024600",  59.65200,  17.91900, "ST", "Stockholm.Arlanda.AP"),
    ("024620",  59.86670,  17.63330, "UP", "Uppsala.Univ"),
    ("024640",  59.35400,  17.94200, "ST", "Stockholm.Bromma.AP"),
    ("024680",  60.38220,  15.14060, "KO", "Stora.Spansberget"),
    ("024690",  59.17890,  17.91280, "ST", "Tullinge.AP"),
    ("024720",  60.12280,  15.12280, "KO", "Skeppmora"),
    ("024740",  60.16700,  18.75000, "ST", "Singo.Island"),
    ("024760",  59.05640,  16.39780, "SD", "Floda"),
    ("024810",  59.90970,  16.68780, "VR", "Sala"),
    ("024820",  60.26890,  16.97720, "UP", "Kerstinbo"),
    ("024850",  59.35000,  18.06670, "ST", "Stockholm"),
    ("024860",  59.35830,  17.52440, "ST", "Adelso"),
    ("024870",  59.34440,  18.74060, "ST", "Skarpo-Stavnas"),
    ("024880",  60.52610,  18.37670, "UP", "Orskar.Lighthouse"),
    ("024890",  59.06780,  18.10890, "ST", "Berga"),
    ("024900",  59.83220,  18.63470, "ST", "Svanberga"),
    ("024930",  59.75260,  19.40550, "ST", "Soderarm"),
    ("024950",  59.55000,  20.01700, "ST", "Svenska.Bjorn.Lighthouse"),
    ("024960",  59.44450,  19.50580, "UP", "Svenska.Hogarna.Lighthouse"),
    ("024990",  59.26670,  19.51670, "ST", "Almagrundet.Lighthouse"),
    ("025000",  58.89190,  11.00390, "VG", "Nordkoster.Natl.Park"),
    ("025010",  58.57610,  11.06610, "VG", "Vaderoarna"),
    ("025040",  58.56700,  11.55000, "VG", "Svarteborg"),
    ("025050",  58.09420,  11.33360, "VG", "Maseskar.Lighthouse"),
    ("025070",  58.66080,  11.41780, "VG", "Hud"),
    ("025100",  58.21700,  11.93300, "VG", "Ljungskile"),
    ("025103",  58.31800,  12.34500, "VG", "Trollhattan.Vanersborg.AP"),
    ("025120",  57.77500,  11.87000, "VG", "Goteborg.City.AP"),
    ("025130",  57.71560,  11.99250, "VG", "Goteborg"),
    ("025150",  58.19970,  12.15420, "VG", "Torpabron"),
    ("025160",  57.63220,  11.60470, "VG", "Vinga.Lighthouse"),
    ("025170",  57.60000,  11.63300, "VG", "Trubaduren"),
    ("025180",  57.30390,  11.90640, "HA", "Nidingen.Lighthouse"),
    ("025200",  58.42890,  12.71390, "VG", "Satenas.AP"),
    ("025210",  58.60030,  12.41310, "VG", "Bergarud"),
    ("025240",  57.93300,  13.06700, "VG", "Molla"),
    ("025260",  57.67610,  12.29190, "VG", "Gothenburg-Landvetter.AP"),
    ("025280",  61.16700,  13.01700, "KO", "Tandadalen"),
    ("025300",  58.90000,  13.25000, "VG", "Nashuvud"),
    ("025330",  58.38300,  13.25000, "VG", "Skara"),
    ("025350",  58.45600,  13.97300, "VG", "Skovde.AP"),
    ("025360",  57.78500,  13.16690, "VG", "Rangedala"),
    ("025361",  57.71700,  13.08300, "VG", "Dalsjofors"),
    ("025390",  57.11360,  12.77580, "HA", "Ullared"),
    ("025400",  58.60690,  12.19750, "VG", "Kroppefjall-Granan"),
    ("025410",  58.96700,  14.90000, "OR", "Snavlunda"),
    ("025420",  58.32220,  13.04060, "VG", "Hallum"),
    ("025440",  58.51360,  14.50720, "VG", "Karlsborg.AP"),
    ("025450",  58.57120,  14.55720, "VG", "Axstal"),
    ("025460",  58.87720,  14.39060, "OR", "Gardsjo"),
    ("025480",  58.09530,  14.40860, "JO", "Visingso"),
    ("025490",  57.49830,  14.46750, "JO", "Tomtabacken"),
    ("025500",  57.75140,  14.06920, "JO", "Jonkoping.AP"),
    ("025520",  58.07190,  15.23610, "OG", "Malexander"),
    ("025530",  58.07940,  13.78500, "VG", "Kymbo"),
    ("025540",  58.71610,  15.03030, "OR", "Kettstaka"),
    ("025550",  57.65000,  14.70000, "JO", "Nassjo"),
    ("025560",  57.29250,  14.14000, "JO", "Hagshult.AP"),
    ("025570",  57.88640,  15.86560, "OG", "Horn"),
    ("025580",  58.68940,  16.31060, "OG", "Kolmarden-Stromsfors"),
    ("025590",  57.70720,  16.45860, "KA", "Gladhammar"),
    ("025610",  58.64030,  15.43360, "OG", "Kvarn"),
    ("025620",  58.39810,  15.52580, "OG", "Malmen.AP"),
    ("025625",  58.40600,  15.68100, "OG", "Linkoping.AP"),
    ("025630",  58.25080,  17.00930, "OG", "Harstena"),
    ("025650",  57.52600,  15.82300, "KA", "Hultsfred.AP"),
    ("025660",  57.38440,  15.80110, "KA", "Malilla"),
    ("025670",  58.73960,  17.86580, "SD", "Landsort.Lighthouse"),
    ("025680",  57.06700,  15.96700, "KA", "Aboda"),
    ("025700",  58.61700,  16.11700, "OG", "Norrkoping-Bravalla"),
    ("025710",  58.58600,  16.25100, "OG", "Norrkoping.AP"),
    ("025720",  58.78300,  16.91700, "SD", "Stockholm.Skavsta.AP-Nykoping"),
    ("025740",  58.58280,  16.14690, "OG", "Norrkoping"),
    ("025750",  57.36680,  17.09760, "KA", "Olands.Norra.Udde"),
    ("025800",  58.96700,  18.45000, "ST", "Stabbo"),
    ("025830",  58.60000,  17.46700, "SD", "Gustaf.Dalen"),
    ("025870",  57.91800,  18.93380, "GT", "Farosund.Ar"),
    ("025880",  57.96000,  19.34800, "GT", "Faro.Island.Lighthouse"),
    ("025890",  58.39450,  19.19780, "GT", "Gotska.Sandon.Island"),
    ("025900",  57.66670,  18.35000, "GT", "Visby.AP"),
    ("025950",  57.54360,  18.42530, "GT", "Roma"),
    ("025980",  57.44140,  18.98440, "GT", "Ostergarnsholm"),
    ("026020",  56.40420,  12.94360, "SN", "Hallandsasen"),
    ("026030",  56.86250,  12.66280, "HA", "Broen"),
    ("026040",  56.69100,  12.82000, "HA", "Halmstad"),
    ("026050",  56.44970,  12.54720, "HA", "Hallands.Vadero"),
    ("026060",  56.30100,  12.45380, "SN", "Kullen.Lighthouse"),
    ("026070",  56.29780,  12.84420, "SN", "Angelholm-Helsingborg.AP"),
    ("026090",  55.47420,  13.66830, "SN", "Rynge"),
    ("026100",  55.86700,  12.86700, "SN", "Orja"),
    ("026110",  56.03060,  12.76530, "SN", "Helsingborg"),
    ("026140",  55.60000,  12.85000, "SN", "Oskarsgrundet"),
    ("026160",  55.38360,  12.81670, "SN", "Falsterbo.Lighthouse"),
    ("026180",  56.94940,  13.06030, "HA", "Torup"),
    ("026220",  56.85280,  13.88220, "KR", "Ljungby"),
    ("026230",  55.86330,  13.66890, "SN", "Horby"),
    ("026250",  55.48830,  14.31460, "SN", "Skillinge"),
    ("026260",  56.37400,  13.93800, "SN", "Osby"),
    ("026280",  56.01390,  14.84940, "BL", "Hano.Island"),
    ("026290",  56.27440,  13.93780, "SN", "Hastveda"),
    ("026320",  55.95270,  15.70140, "BL", "Utklippan.Lighthouse"),
    ("026330",  55.71390,  13.21220, "SN", "Lund.Sol"),
    ("026350",  55.57140,  13.07360, "SN", "Malmo"),
    ("026360",  55.52310,  13.37890, "SN", "Malmo.AP-Sturup"),
    ("026380",  55.33850,  13.35280, "SN", "Smygehuk.Lighthouse"),
    ("026410",  56.92900,  14.72800, "KR", "Vaxjo.Smaland.AP"),
    ("026440",  56.19720,  16.39930, "KA", "Olands.Sodra.Udde.Lighthouse"),
    ("026460",  56.66700,  16.46080, "KA", "Olandsbron.Bridge"),
    ("026480",  56.84640,  14.83250, "KR", "Vaxjo"),
    ("026510",  55.92200,  14.08600, "SN", "Kristianstad.AP"),
    ("026520",  56.02390,  14.10280, "SN", "Kristianstad"),
    ("026531",  55.98300,  14.30000, "SN", "Rinkaby.AF"),
    ("026540",  55.66700,  14.26700, "SN", "Stenshuvud.National.Park"),
    ("026610",  56.84500,  15.47220, "KR", "Kosta.Orrefors"),
    ("026640",  56.26690,  15.26810, "BL", "Ronneby.AP"),
    ("026660",  56.04100,  15.80400, "BL", "Ungskar"),
    ("026670",  56.15710,  15.57970, "BL", "Karlskrona-Soderstjerna"),
    ("026700",  56.68330,  16.30000, "KA", "Kalmar.AP"),
    ("026790",  56.92110,  18.15060, "GT", "Hoburg.Lighthouse"),
    ("026850",  56.06700,  16.68300, "KA", "Olands.Sodra.Grund"),
]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two WGS-84 points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _epw_filename(region: str, name: str, wmo: str, period: str) -> str:
    """Build OneBuilding EPW filename."""
    suffix = f".{period}" if period else ""
    return f"SWE_{region}_{name}.{wmo}_TMYx{suffix}.epw"


def nearest_epw(
    lat: float,
    lon: float,
    period: str = DEFAULT_PERIOD,
    epw_dir: Path | None = None,
) -> Path:
    """Return the path to the nearest local EPW file for a WGS-84 coordinate.

    Parameters
    ----------
    lat, lon : float
        Building location in WGS-84 decimal degrees.
    period : str
        TMY period, e.g. ``"2011-2025"``. Empty string for base TMYx.
    epw_dir : Path, optional
        Directory containing the EPW files.  Defaults to ``<repo>/epw/``.
    """
    d = epw_dir or _EPW_DIR
    best, best_dist = _STATIONS[0], float("inf")
    for s in _STATIONS:
        dist = _haversine_km(lat, lon, s[1], s[2])
        if dist < best_dist:
            best, best_dist = s, dist
    wmo, _, _, region, name = best
    return d / _epw_filename(region, name, wmo, period)


def sweref99tm_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """Convert EPSG:3006 (SWEREF99 TM) to WGS-84 (lat, lon) via pyproj."""
    from pyproj import Transformer
    _tx = Transformer.from_crs("EPSG:3006", "EPSG:4326", always_xy=True)
    lon, lat = _tx.transform(x, y)
    return lat, lon


def nearest_epw_from_footprint(
    footprint_pts: list[list[float]],
    period: str = DEFAULT_PERIOD,
    epw_dir: Path | None = None,
) -> Path:
    """Pick the nearest EPW given an EPSG:3006 footprint polygon.

    Computes the centroid and converts to WGS-84 before lookup.
    """
    xs = [p[0] for p in footprint_pts]
    ys = [p[1] for p in footprint_pts]
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    lat, lon = sweref99tm_to_wgs84(cx, cy)
    return nearest_epw(lat, lon, period, epw_dir)
