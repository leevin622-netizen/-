"""
קוד ה-JavaScript של העמודים. נכנס לעמוד עצמו (ולא כקובץ נפרד), כי חלק מהטקסטים בו מתורגמים לפי שפת הממשק.
"""

# מיון טבלה בלחיצה על כותרת, וסינון לפי טקסט חופשי
# כפתור "שם אחר": עובר בין הצעות השמות
NAME_JS = """
var nameButton = document.getElementById("other-name");
if (nameButton) {
  var names = JSON.parse(nameButton.dataset.names), current = 0;
  nameButton.addEventListener("click", function () {
    current = (current + 1) % names.length;
    document.getElementById("title").value = names[current];
  });
}
"""


# מיון התצוגה המקדימה לפי שם, אמן, אורך, שנה, BPM, אנרגיה או שמחה. מעבירים שירים למעלה ולמטה, ומערבבים
# כל קטע עטוף בפונקציה, כדי שהמשתנים לא יתנגשו עם קטעי JavaScript אחרים בעמוד
SORT_JS = """
(function () {
  var list = document.getElementById("playlist"), sortSelect = document.getElementById("sort");
  var shuffleButton = document.getElementById("shuffle");
  // סוג המיון לכל שדה: טקסט, מספר שעולה, או מספר שיורד
  var sortKinds = { name: "text", artist: "text", duration: "asc", year: "asc", bpm: "desc", energy: "desc", valence: "desc" };
  function number(value, kind) {
    var n = parseFloat(value);
    if (!isNaN(n)) return n;
    return kind === "asc" ? Infinity : -Infinity;
  }
  if (!list) return;
  var originalOrder = Array.from(list.children);
  if (sortSelect) {
    sortSelect.addEventListener("change", function () {
      var key = sortSelect.value, kind = sortKinds[key];
      var items = key ? Array.from(list.children).sort(function (a, b) {
        var x = a.dataset[key] || "", y = b.dataset[key] || "";
        if (kind === "text") return x.localeCompare(y, "he");
        var nx = number(x, kind), ny = number(y, kind);
        if (nx === ny) return 0;
        return (kind === "asc" ? nx < ny : nx > ny) ? -1 : 1;
      }) : originalOrder;
      items.forEach(function (li) { list.appendChild(li); });
    });
  }
  list.addEventListener("click", function (event) {
    var button = event.target.closest(".move");
    if (!button) return;
    var li = button.closest("li"), dir = Number(button.dataset.dir);
    if (dir < 0 && li.previousElementSibling) list.insertBefore(li, li.previousElementSibling);
    if (dir > 0 && li.nextElementSibling) list.insertBefore(li.nextElementSibling, li);
    if (sortSelect) sortSelect.value = "";
  });
  if (shuffleButton) {
    shuffleButton.addEventListener("click", function () {
      var items = Array.from(list.children);
      for (var i = items.length - 1; i > 0; i--) {
        var j = Math.floor(Math.random() * (i + 1)), t = items[i];
        items[i] = items[j]; items[j] = t;
      }
      items.forEach(function (li) { list.appendChild(li); });
      if (sortSelect) sortSelect.value = "";
    });
  }
})();
"""


# כפתור ▶ לכל שיר, בתצוגה המקדימה ובטבלת השירים שאהבת. הכתובת נטענת מהשרת רק בלחיצה.
# אם אין קטע ב-Deezer או ב-iTunes, נפתח בתחתית המסך נגן ספוטיפיי של השיר, שעובד לכל שיר
LAZY_PLAY_JS = """
(function () {
  var player = new Audio(), playingButton = null, bar = null;
  function spotifyBar(id) {
    if (!bar) {
      bar = document.createElement("div");
      bar.className = "sp-bar";
      bar.innerHTML = '<button type="button" class="sp-close" aria-label="סגירת הנגן">✕</button><iframe title="נגן ספוטיפיי" allow="autoplay; encrypted-media"></iframe>';
      bar.querySelector(".sp-close").addEventListener("click", function () {
        bar.hidden = true;
        bar.querySelector("iframe").src = "about:blank";
      });
      document.body.appendChild(bar);
    }
    bar.hidden = false;
    bar.querySelector("iframe").src = "https://open.spotify.com/embed/track/" + encodeURIComponent(id) + "?utm_source=generator&theme=0";
  }
  function stop() {
    player.pause();
    if (playingButton) {
      playingButton.classList.remove("playing");
      playingButton.setAttribute("aria-pressed", "false");
      playingButton.textContent = "▶";
    }
    playingButton = null;
  }
  function start(button, url) {
    stop();
    player.src = url;
    playingButton = button;
    button.classList.add("playing");
    button.setAttribute("aria-pressed", "true");
    button.textContent = "⏸";
    player.play().catch(stop);
  }
  player.addEventListener("ended", stop);
  document.addEventListener("click", function (event) {
    var button = event.target.closest(".play[data-title]");
    if (!button || button.classList.contains("loading")) return;
    if (playingButton === button) { stop(); return; }
    if (button.dataset.found) { start(button, button.dataset.found); return; }
    if (button.dataset.missing) { stop(); spotifyBar(button.dataset.id); return; }
    button.classList.add("loading");
    var query = new URLSearchParams({ artist: button.dataset.artist, title: button.dataset.title });
    fetch("/preview?" + query).then(function (r) { return r.json(); }).then(function (data) {
      button.classList.remove("loading");
      if (!data.url) {
        button.dataset.missing = "1";
        if (button.dataset.id) { stop(); spotifyBar(button.dataset.id); return; }
        button.classList.add("none");
        button.textContent = "–";
        button.title = "לא נמצא קטע לשיר הזה";
        button.setAttribute("aria-label", "לא נמצא קטע לשיר הזה");
        return;
      }
      button.dataset.found = data.url;
      start(button, data.url);
    }).catch(function () { button.classList.remove("loading"); });
  });
})();
"""


# העתקת כרטיס השיתוף של הסטטיסטיקות
COPY_JS = """
(function () {
  var copyButton = document.getElementById("copy-card"), box = document.getElementById("card-text");
  if (!copyButton || !box) return;
  copyButton.addEventListener("click", function () {
    box.select();
    function done() { copyButton.textContent = "✅ הועתק"; }
    if (navigator.clipboard) { navigator.clipboard.writeText(box.value).then(done); }
    else { document.execCommand("copy"); done(); }
  });
})();
"""


# כרטיס השיתוף הוא SVG. מציירים אותו על קנבס בגודל המלא שלו ומורידים כ-PNG, או משתפים (בטלפון: סטורי, וואטסאפ)
SAVE_CARD_JS = """
(function () {
  var saveButton = document.getElementById("save-card"), shareButton = document.getElementById("share-card");
  var svg = document.getElementById("card-svg"), box = document.getElementById("card-text");
  if (!saveButton || !svg) return;
  var width = Number(svg.getAttribute("width")), height = Number(svg.getAttribute("height"));
  function makePng(done) {
    var source = new XMLSerializer().serializeToString(svg);
    var svgUrl = URL.createObjectURL(new Blob([source], { type: "image/svg+xml;charset=utf-8" }));
    var image = new Image();
    image.onload = function () {
      var canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      canvas.getContext("2d").drawImage(image, 0, 0, width, height);
      URL.revokeObjectURL(svgUrl);
      canvas.toBlob(done, "image/png");
    };
    image.src = svgUrl;
  }
  saveButton.addEventListener("click", function () {
    makePng(function (png) {
      var link = document.createElement("a");
      link.href = URL.createObjectURL(png);
      link.download = "playlistor-card.png";
      document.body.appendChild(link);
      link.click();
      link.remove();
    });
  });
  // שיתוף עם התמונה, רק בדפדפנים שתומכים בשיתוף קבצים (בעיקר בטלפון)
  var probe = new File([""], "card.png", { type: "image/png" });
  if (shareButton && navigator.canShare && navigator.canShare({ files: [probe] })) {
    shareButton.hidden = false;
    shareButton.addEventListener("click", function () {
      makePng(function (png) {
        var file = new File([png], "playlistor-card.png", { type: "image/png" });
        navigator.share({ files: [file], text: box ? box.value : "" }).catch(function () {});
      });
    });
  }
})();
"""


# בדיקה לפני שליחה: לפחות ז'אנר, מצב רוח או אירוע. השרת בודק שוב (ראו build)
BUILD_CHECK_JS = """
(function () {
  var form = document.getElementById("build-form"), box = document.getElementById("build-error");
  var group = document.getElementById("must-pick");
  if (!form) return;
  form.addEventListener("submit", function (event) {
    var picked = ["genre_choice", "mood", "event"].some(function (name) {
      return form.elements[name].value.trim() !== "";
    });
    if (picked) return;
    event.preventDefault();
    box.textContent = __MESSAGE__;
    box.hidden = false;
    group.classList.add("invalid");
    group.scrollIntoView({ behavior: "smooth", block: "center" });
  });
  form.addEventListener("change", function () { group.classList.remove("invalid"); box.hidden = true; });
})();
"""


TABLE_JS = """
// ערך המיון של תא: data-v כשיש (מספרים, תאריכים), ואחרת הטקסט שמוצג
function sortValue(cell) {
  return cell.dataset.v !== undefined ? cell.dataset.v : cell.textContent.trim();
}
document.querySelectorAll("table.sortable").forEach(function (table) {
  var body = table.tBodies[0];
  table.querySelectorAll("th[data-type]").forEach(function (th, col) {
    th.tabIndex = 0;
    th.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); th.click(); }
    });
    th.addEventListener("click", function () {
      var desc = !th.classList.contains("desc");
      table.querySelectorAll("th").forEach(function (h) { h.classList.remove("asc", "desc"); h.removeAttribute("aria-sort"); });
      th.classList.add(desc ? "desc" : "asc");
      th.setAttribute("aria-sort", desc ? "descending" : "ascending");
      var numeric = th.dataset.type === "num";
      var rows = Array.from(body.rows);
      rows.sort(function (a, b) {
        var x = sortValue(a.cells[th.cellIndex]), y = sortValue(b.cells[th.cellIndex]);
        if (numeric) {
          x = x === "" ? -Infinity : parseFloat(x); y = y === "" ? -Infinity : parseFloat(y);
          return desc ? y - x : x - y;
        }
        return desc ? y.localeCompare(x, "he") : x.localeCompare(y, "he");
      });
      rows.forEach(function (r) { body.appendChild(r); });
    });
  });
});
document.querySelectorAll("[data-check-visible]").forEach(function (button) {
  button.addEventListener("click", function () {
    var body = document.getElementById(button.dataset.checkVisible).tBodies[0];
    var check = button.dataset.state !== "on";
    Array.from(body.rows).forEach(function (r) {
      if (r.style.display !== "none") { r.querySelector("input[type=checkbox]").checked = check; }
    });
    button.dataset.state = check ? "on" : "off";
    button.textContent = check ? "בטל סימון של המוצגים" : "סמן את כל המוצגים";
  });
});
document.querySelectorAll("input.search").forEach(function (input) {
  var body = document.getElementById(input.dataset.table).tBodies[0];
  input.addEventListener("input", function () {
    var q = input.value.trim().toLowerCase();
    Array.from(body.rows).forEach(function (r) {
      r.style.display = r.textContent.toLowerCase().indexOf(q) === -1 ? "none" : "";
    });
  });
});
"""


CATALOG_JS = """
(function () {
  // השרת מסנן ושולח 60 כרטיסים בכל פעם. כאן רק מבקשים עוד, או מסננים מחדש
  var T = __T__;
  var grid = document.getElementById('pl-grid');
  var count = document.getElementById('pl-count'), more = document.getElementById('pl-more');
  var box = document.getElementById('pl-search');
  function initial(group) {
    var chip = document.querySelector('[data-group="' + group + '"][aria-pressed="true"]');
    return chip ? chip.dataset.value : '';
  }
  var state = {cat: initial('cat'), market: initial('market'), shown: +grid.dataset.shown, total: +grid.dataset.total};
  var request = 0, timer = null;
  function show() {
    count.textContent = T.count.replace('{a}', state.shown).replace('{b}', state.total);
    more.hidden = state.shown >= state.total;
  }
  function load(append) {
    var mine = ++request;
    var query = new URLSearchParams({cat: state.cat, market: state.market, q: box.value.trim(),
                                     offset: append ? state.shown : 0});
    more.disabled = true;
    fetch('/existing-playlists/cards?' + query)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (mine !== request) return;
        if (append) { grid.insertAdjacentHTML('beforeend', data.html); } else { grid.innerHTML = data.html; }
        state.shown = data.next;
        state.total = data.total;
        show();
      })
      .catch(function () { alert(T.load_failed); })
      .then(function () { more.disabled = false; });
  }
  function pick(group, key) {
    [].forEach.call(document.querySelectorAll('[data-group="' + group + '"]'), function (chip) {
      chip.setAttribute('aria-pressed', chip.dataset.value === state[key] ? 'true' : 'false');
    });
  }
  [].forEach.call(document.querySelectorAll('.chip'), function (chip) {
    chip.addEventListener('click', function () {
      var key = chip.dataset.group === 'cat' ? 'cat' : 'market';
      state[key] = chip.dataset.value;
      pick(chip.dataset.group, key);
      load(false);
    });
  });
  // חיפוש אחרי הפסקה קצרה בהקלדה, ולא על כל אות
  box.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(function () { load(false); }, 250); });
  more.addEventListener('click', function () { load(true); });
  grid.addEventListener('click', function (event) {
    var button = event.target.closest('.add');
    if (!button || button.disabled) return;
    button.disabled = true;
    var data = new FormData();
    data.append('csrf', grid.dataset.csrf);
    data.append('id', button.dataset.id);
    fetch('/existing-playlists/follow', {method: 'POST', body: data})
      .then(function (r) { return r.json(); })
      .then(function (r) {
        if (r.ok) { button.textContent = T.added; } else { button.disabled = false; alert(T.failed); }
      })
      .catch(function () { button.disabled = false; alert(T.failed); });
  });
  show();
})();
"""


EDIT_JS = """
(function () {
  // עריכת פלייליסט בלי לטעון את הדף מחדש: הזזה והסרה נשלחות ברקע, והרשימה מתעדכנת במקום.
  // כל שינוי מחכה שהקודם יסתיים, כי המיקומים משתנים אחרי כל הזזה
  var T = __T__;
  var list = document.getElementById("pl-edit");
  if (!list) return;
  var size = document.getElementById("pl-size"), busy = false;
  var bar = document.createElement("div"), pending = null, timer = null;
  bar.className = "undo-bar";
  bar.setAttribute("role", "status");
  bar.hidden = true;
  list.parentNode.insertBefore(bar, list);
  function renumber() {
    var rows = list.children;
    Array.prototype.forEach.call(rows, function (li, i) {
      li.dataset.position = i;
      li.querySelectorAll("input[name=position]").forEach(function (input) { input.value = i; });
      var buttons = li.querySelectorAll("form[action$='/move'] button");
      buttons[0].disabled = i === 0;
      buttons[1].disabled = i === rows.length - 1;
    });
    if (size) size.textContent = rows.length;
  }
  function clearUndo() {
    pending = null;
    clearTimeout(timer);
    bar.hidden = true;
    bar.textContent = "";
  }
  // אחרי הסרה אפשר לבטל: השיר חוזר למקום שבו היה. כל פעולה אחרת מבטלת את האפשרות, כי המיקומים משתנים
  function offerUndo(li, form) {
    clearUndo();
    var title = li.querySelector(".title");
    pending = {
      li: li, index: Number(form.elements.position.value), uri: form.elements.uri.value,
      csrf: form.elements.csrf.value, url: form.action.replace(/remove$/, "restore")
    };
    var text = document.createElement("span");
    text.textContent = T.removed.replace("{a0}", title ? title.textContent : "");
    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn secondary";
    button.textContent = T.undo;
    button.addEventListener("click", undo);
    bar.appendChild(text);
    bar.appendChild(button);
    bar.hidden = false;
    timer = setTimeout(clearUndo, 10000);
  }
  function undo() {
    if (busy || !pending) return;
    busy = true;
    var item = pending, body = new FormData();
    body.append("csrf", item.csrf);
    body.append("uri", item.uri);
    body.append("position", item.index);
    fetch(item.url, {method: "POST", body: body, headers: {"X-Requested-With": "fetch"}})
      .then(function (r) { return r.ok ? r.json() : {ok: false}; })
      .then(function (r) {
        if (!r.ok) throw new Error("failed");
        list.insertBefore(item.li, list.children[item.index] || null);
        clearUndo();
        renumber();
      })
      .catch(function () {
        alert(T.failed);
        location.reload();
      })
      .then(function () { busy = false; });
  }
  list.addEventListener("submit", function (event) {
    var form = event.target;
    event.preventDefault();
    if (busy) return;
    busy = true;
    clearUndo();
    var li = form.closest("li");
    var direction = form.elements.direction ? form.elements.direction.value : "";
    li.classList.add("saving");
    fetch(form.action, {method: "POST", body: new FormData(form), headers: {"X-Requested-With": "fetch"}})
      .then(function (r) { return r.ok ? r.json() : {ok: false}; })
      .then(function (r) {
        if (!r.ok) throw new Error("failed");
        if (form.action.endsWith("/remove")) {
          var playing = li.querySelector(".play.playing");
          if (playing) playing.click();
          li.remove();
          offerUndo(li, form);
        } else if (direction === "up" && li.previousElementSibling) {
          list.insertBefore(li, li.previousElementSibling);
        } else if (direction === "down" && li.nextElementSibling) {
          list.insertBefore(li.nextElementSibling, li);
        }
        renumber();
      })
      .catch(function () {
        alert(T.failed);
        location.reload();
      })
      .then(function () { busy = false; li.classList.remove("saving"); });
  });
})();
"""


SAVED_JS = """
(function () {
  // הטבלה של "כל השירים שאהבתי" נבנית כאן מהנתונים המקוצרים שבעמוד (tracks-data),
  // במקום לקבל אלפי שורות HTML מוכנות מהשרת. כל שורה: [uri, שם, [[id, אמן]...], id אלבום, אלבום,
  // תמונה, תאריך הוספה, אורך במילישניות, מקום בדירוג (0 אם אין), תווית הדירוג]
  var T = __T__;
  var IMAGE = "https://i.scdn.co/image/", OPEN = "https://open.spotify.com/";
  var data = JSON.parse(document.getElementById("tracks-data").textContent);
  function esc(text) {
    return String(text).replace(/[&<>"']/g, function (c) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;"}[c];
    });
  }
  function link(text, kind, id, inner) {
    var content = inner || esc(text);
    if (!id) return content;
    return '<a class="sp" href="' + OPEN + kind + "/" + esc(id) + '" target="_blank"' +
      (text ? "" : ' aria-label="' + esc(T.open) + '"') + ">" + content + "</a>";
  }
  function cover(image) {
    if (!image) return '<div class="noimg"></div>';
    return '<img src="' + esc(image.indexOf("://") < 0 ? IMAGE + image : image) + '" alt="" loading="lazy">';
  }
  function duration(ms) {
    var s = Math.floor(ms / 1000), r = s % 60;
    return Math.floor(s / 60) + ":" + (r < 10 ? "0" : "") + r;
  }
  function shortDate(d) {
    return d.length === 10 ? d.slice(8, 10) + "." + d.slice(5, 7) + "." + d.slice(2, 4) : d;
  }
  var rows = data.map(function (t) {
    var uri = t[0], name = t[1], artists = t[2], id = uri.indexOf("spotify:track:") === 0 ? uri.slice(14) : "";
    var first = artists.length ? artists[0][1] : "";
    return "<tr><td><input type=\\"checkbox\\" name=\\"uri\\" value=\\"" + esc(uri) + "\\" aria-label=\\"" +
      esc(T.check.replace("{a0}", name)) + "\\"></td>" +
      "<td><button type=\\"button\\" class=\\"play\\" data-artist=\\"" + esc(first) + "\\" data-title=\\"" + esc(name) +
      "\\" data-id=\\"" + esc(id) + "\\" aria-pressed=\\"false\\" aria-label=\\"" + esc(T.play.replace("{a0}", name)) +
      "\\">▶</button></td>" +
      "<td>" + link("", "album", t[3], cover(t[5])) + "</td>" +
      "<td class=\\"name\\">" + link(name, "track", id) + "</td>" +
      "<td class=\\"short\\">" + artists.map(function (a) { return link(a[1], "artist", a[0]); }).join(", ") + "</td>" +
      "<td class=\\"short muted\\">" + link(t[4], "album", t[3]) + "</td>" +
      "<td class=\\"muted\\" data-v=\\"" + esc(t[6]) + "\\">" + esc(shortDate(t[6])) + "</td>" +
      "<td class=\\"muted\\" data-v=\\"" + t[7] + "\\">" + duration(t[7]) + "</td>" +
      // בדירוג, מקום 1 הוא הכי טוב, ולכן ממיינים לפי מספר שלילי
      "<td class=\\"muted\\" data-v=\\"" + (t[8] ? -t[8] : "") + "\\">" + esc(t[9]) + "</td></tr>";
  });
  document.getElementById("tracks").tBodies[0].innerHTML = rows.join("");
})();
"""
