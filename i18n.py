"""
תרגום הממשק ל-5 שפות: עברית (ברירת מחדל), אנגלית, ספרדית, ערבית ורוסית.
השפה נשמרת בסשן של המשתמש, ונבחרת בעמוד הבית. טקסט שחסר בשפה נופל לעברית.
"""
from flask import session

CODES = ["he", "en", "es", "ar", "ru"]
NAMES = {"he": "עברית", "en": "English", "es": "Español", "ar": "العربية", "ru": "Русский"}
RTL = {"he", "ar"}

THEME_LABELS = {
    "pop": {"he": "פופ", "en": "Pop", "es": "Pop", "ar": "بوب", "ru": "Поп"},
    "mizrahi": {"he": "מזרחית", "en": "Mizrahi", "es": "Mizrají", "ar": "مزراحي", "ru": "Мизрахи"},
    "rock": {"he": "רוק", "en": "Rock", "es": "Rock", "ar": "روك", "ru": "Рок"},
    "hiphop": {"he": "היפ הופ", "en": "Rap", "es": "Rap", "ar": "راب", "ru": "Рэп"},
    "electronic": {"he": "אלקטרוני", "en": "Dance", "es": "Baile", "ar": "رقص", "ru": "Танцы"},
    "chill": {"he": "צ'יל", "en": "Chill", "es": "Chill", "ar": "هادئ", "ru": "Чилл"},
    "default": {"he": "מיקס", "en": "Mix", "es": "Mezcla", "ar": "مزيج", "ru": "Микс"},
}

STRINGS = {
    "login.title": {
        "he": "פלייליסטים שמתאימים בדיוק לרגע",
        "en": "Playlists that fit the moment",
        "es": "Listas que encajan con el momento",
        "ar": "قوائم تناسب اللحظة تمامًا",
        "ru": "Плейлисты, которые подходят к моменту",
    },
    "login.note": {
        "he": "בחרו ז'אנר, מצב רוח ואירוע, ופלייליסטור יבנה לכם פלייליסט חדש בספוטיפיי.",
        "en": "Pick a genre, a mood and an event, and Playlistor will build a new playlist in Spotify.",
        "es": "Elige un género, un estado de ánimo y un evento, y Playlistor creará una lista nueva en Spotify.",
        "ar": "اختر نوعًا وحالة مزاجية ومناسبة، وسينشئ Playlistor قائمة جديدة في Spotify.",
        "ru": "Выберите жанр, настроение и событие, и Playlistor создаст новый плейлист в Spotify.",
    },
    "login.button": {
        "he": "התחברות עם ספוטיפיי",
        "en": "Log in with Spotify",
        "es": "Iniciar sesión con Spotify",
        "ar": "تسجيل الدخول عبر Spotify",
        "ru": "Войти через Spotify",
    },
    "home.title": {
        "he": "מה נשמע היום?",
        "en": "What's playing today?",
        "es": "¿Qué suena hoy?",
        "ar": "ماذا نسمع اليوم؟",
        "ru": "Что звучит сегодня?",
    },
    "vibe.now": {
        "he": "הווייב שלך עכשיו:",
        "en": "Your vibe right now:",
        "es": "Tu vibra ahora:",
        "ar": "أجواؤك الآن:",
        "ru": "Ваш вайб сейчас:",
    },
    "vibe.auto": {
        "he": "בול מה שהכי מתנגן אצלך לאחרונה 🔥",
        "en": "Exactly what you've been playing lately 🔥",
        "es": "Justo lo que más suena últimamente 🔥",
        "ar": "بالضبط ما تستمع إليه مؤخرًا 🔥",
        "ru": "Именно то, что вы слушаете в последнее время 🔥",
    },
    "vibe.other": {
        "he": "מה שהכי מתנגן אצלך: {emoji} {label} · אפשר להחליף בתפריט למעלה",
        "en": "What you play most: {emoji} {label} · change it in the menu above",
        "es": "Lo que más escuchas: {emoji} {label} · cámbialo en el menú de arriba",
        "ar": "ما تستمع إليه أكثر: {emoji} {label} · يمكنك تغييره من القائمة أعلاه",
        "ru": "Что вы слушаете чаще всего: {emoji} {label} · можно сменить в меню выше",
    },
    "menu.build.title": {
        "he": "צור פלייליסט חדש", "en": "Create a new playlist", "es": "Crear una lista nueva",
        "ar": "إنشاء قائمة جديدة", "ru": "Создать новый плейлист",
    },
    "menu.build.small": {
        "he": "לפי ז'אנר, מצב רוח, אירוע ושפה, מכל ספוטיפיי או מהשירים שאהבתי",
        "en": "By genre, mood, event and language, from all of Spotify or your liked songs",
        "es": "Por género, estado de ánimo, evento e idioma, de todo Spotify o de tus favoritas",
        "ar": "حسب النوع والحالة المزاجية والمناسبة واللغة، من كل Spotify أو من أغانيك المفضلة",
        "ru": "По жанру, настроению, событию и языку — из всего Spotify или из любимых треков",
    },
    "menu.saved.title": {
        "he": "כל השירים שאהבתי", "en": "All my liked songs", "es": "Todas mis canciones favoritas",
        "ar": "كل أغانيّ المفضلة", "ru": "Все мои любимые треки",
    },
    "menu.saved.small": {
        "he": "הרשימה המלאה, עם השמעת קטעים ומיון לפי אמן, תאריך ועוד",
        "en": "The full list, with clips and sorting by artist, date and more",
        "es": "La lista completa, con fragmentos y orden por artista, fecha y más",
        "ar": "القائمة الكاملة، مع المقاطع والترتيب حسب الفنان والتاريخ وغير ذلك",
        "ru": "Полный список с фрагментами и сортировкой по исполнителю, дате и другому",
    },
    "menu.artists.title": {
        "he": "כל האמנים שאני אוהב", "en": "All the artists I love", "es": "Todos los artistas que me gustan",
        "ar": "كل الفنانين الذين أحبهم", "ru": "Все исполнители, которые мне нравятся",
    },
    "menu.artists.small": {
        "he": "מי שאני עוקב אחריו, שומע הכי הרבה, או אוהב את השירים שלו",
        "en": "Artists I follow, listen to most, or love the songs of",
        "es": "Artistas que sigo, que más escucho o cuyas canciones me gustan",
        "ar": "فنانون أتابعهم، أو أستمع إليهم أكثر، أو تعجبني أغانيهم",
        "ru": "Исполнители, на которых я подписан, которых слушаю чаще всего или чьи песни мне нравятся",
    },
    "menu.stats.title": {
        "he": "הסטטיסטיקות שלי", "en": "My stats", "es": "Mis estadísticas",
        "ar": "إحصاءاتي", "ru": "Моя статистика",
    },
    "menu.stats.small": {
        "he": "ז'אנרים, עשורים, אמנים מובילים וכרטיס לשיתוף",
        "en": "Genres, decades, top artists and a share card",
        "es": "Géneros, décadas, artistas principales y una tarjeta para compartir",
        "ar": "الأنواع والعقود وأبرز الفنانين وبطاقة للمشاركة",
        "ru": "Жанры, десятилетия, топ исполнителей и карточка для публикации",
    },
    "menu.mine.title": {
        "he": "הפלייליסטים שיצרתי", "en": "Playlists I made", "es": "Listas que creé",
        "ar": "القوائم التي أنشأتها", "ru": "Мои плейлисты",
    },
    "menu.mine.small": {
        "he": "שינוי שם, הסרת שירים וסידור",
        "en": "Rename, remove songs and reorder",
        "es": "Cambiar el nombre, quitar canciones y ordenar",
        "ar": "تغيير الاسم وإزالة الأغاني وإعادة الترتيب",
        "ru": "Переименование, удаление треков и порядок",
    },
    "home.refresh": {
        "he": "רענון נתונים מספוטיפיי", "en": "Refresh data from Spotify", "es": "Actualizar datos de Spotify",
        "ar": "تحديث البيانات من Spotify", "ru": "Обновить данные из Spotify",
    },
    "home.delete": {
        "he": "מחיקת הנתונים שלי מהשרת", "en": "Delete my data from the server",
        "es": "Borrar mis datos del servidor", "ar": "حذف بياناتي من الخادم", "ru": "Удалить мои данные с сервера",
    },
    "build.title": {
        "he": "צור פלייליסט", "en": "Create a playlist", "es": "Crear una lista",
        "ar": "إنشاء قائمة", "ru": "Создать плейлист",
    },
    "build.source": {
        "he": "מאיפה לקחת שירים", "en": "Where to get songs", "es": "De dónde sacar canciones",
        "ar": "من أين نأخذ الأغاني", "ru": "Откуда брать треки",
    },
    "build.source_search": {
        "he": "🌍 מכל ספוטיפיי", "en": "🌍 From all of Spotify", "es": "🌍 De todo Spotify",
        "ar": "🌍 من كل Spotify", "ru": "🌍 Из всего Spotify",
    },
    "build.source_liked": {
        "he": "❤️ רק מהשירים שאהבתי", "en": "❤️ Only from my liked songs", "es": "❤️ Solo de mis favoritas",
        "ar": "❤️ من أغانيّ المفضلة فقط", "ru": "❤️ Только из любимых треков",
    },
    "build.must": {
        "he": "מה מתאים לכם?", "en": "What fits you?", "es": "¿Qué te encaja?",
        "ar": "ما الذي يناسبك؟", "ru": "Что вам подходит?",
    },
    "build.must_note": {
        "he": "חובה לבחור לפחות אחד מהשלושה.", "en": "Pick at least one of the three.",
        "es": "Elige al menos una de las tres.", "ar": "اختر واحدًا على الأقل من الثلاثة.",
        "ru": "Выберите хотя бы один из трёх.",
    },
    "build.genre": {
        "he": "🎵 ז'אנר", "en": "🎵 Genre", "es": "🎵 Género", "ar": "🎵 النوع", "ru": "🎵 Жанр",
    },
    "build.mood": {
        "he": "😊 מצב רוח", "en": "😊 Mood", "es": "😊 Estado de ánimo", "ar": "😊 الحالة المزاجية", "ru": "😊 Настроение",
    },
    "build.event": {
        "he": "📍 אירוע או סיטואציה", "en": "📍 Event or situation", "es": "📍 Evento o situación",
        "ar": "📍 المناسبة أو الموقف", "ru": "📍 Событие или ситуация",
    },
    "build.language": {
        "he": "🗣 שפה", "en": "🗣 Language", "es": "🗣 Idioma", "ar": "🗣 اللغة", "ru": "🗣 Язык",
    },
    "build.decade_from": {
        "he": "📅 מעשור", "en": "📅 From decade", "es": "📅 Desde la década", "ar": "📅 من عقد", "ru": "📅 С десятилетия",
    },
    "build.decade_to": {
        "he": "עד עשור", "en": "To decade", "es": "Hasta la década", "ar": "إلى عقد", "ru": "По десятилетие",
    },
    "build.count": {
        "he": "כמות שירים", "en": "Number of songs", "es": "Número de canciones", "ar": "عدد الأغاني", "ru": "Количество треков",
    },
    "build.count_hint": {
        "he": "בין 5 ל-{max}", "en": "Between 5 and {max}", "es": "Entre 5 y {max}", "ar": "بين 5 و{max}", "ru": "От 5 до {max}",
    },
    "build.personal": {
        "he": "לשלב שירים של האמנים המועדפים עליי", "en": "Include songs from my favourite artists",
        "es": "Incluir canciones de mis artistas favoritos", "ar": "تضمين أغانٍ من فناني المفضلين",
        "ru": "Добавить треки моих любимых исполнителей",
    },
    "build.submit": {
        "he": "✨ הצג שירים", "en": "✨ Show songs", "es": "✨ Mostrar canciones", "ar": "✨ عرض الأغاني", "ru": "✨ Показать треки",
    },
    "common.required": {
        "he": "שדה חובה", "en": "Required field", "es": "Campo obligatorio", "ar": "حقل مطلوب", "ru": "Обязательное поле",
    },
}


def lang():
    code = session.get("lang")
    return code if code in CODES else "he"


def direction():
    return "rtl" if lang() in RTL else "ltr"


def t(key, **values):
    entry = STRINGS[key]
    text = entry.get(lang()) or entry["he"]
    return text.format(**values) if values else text


def theme_label(theme):
    return THEME_LABELS.get(theme, THEME_LABELS["default"])[lang()]


def language_links():
    """קישורים לבחירת שפה. השפה הנוכחית מסומנת לקוראי מסך."""
    current = lang()
    links = []
    for code in CODES:
        current_attr = ' aria-current="true"' if code == current else ""
        links.append(f'<a href="/lang/{code}" lang="{code}"{current_attr}>{NAMES[code]}</a>')
    return '<nav class="langs" aria-label="Language / שפה">' + "".join(links) + "</nav>"
