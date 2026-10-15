/* Поиск по сайту: клиентский, по индексу /search-index.json (его строит build.py).
   Функция search(index, query) — чистая, подключается и в браузере, и в node (module.exports). */
(function (root) {
    "use strict";

    var WEIGHTS = {title: 10, headings: 5, products: 4, description: 3, text: 1};
    var MAX_RESULTS = 20;
    // предлоги и союзы, которые не несут смысла запроса
    var STOP = {"на": 1, "с": 1, "со": 1, "для": 1, "и": 1, "в": 1, "во": 1, "по": 1, "из": 1, "к": 1,
        "от": 1, "под": 1, "при": 1, "без": 1, "или": 1, "за": 1, "о": 1, "у": 1, "а": 1, "что": 1, "как": 1, "до": 1};

    // Нормализация: нижний регистр, ё -> е, всё кроме букв и цифр -> пробел.
    // Замена посимвольная 1:1, поэтому позиции в нормализованной строке совпадают с исходной.
    function normalize(s) {
        return String(s || "").toLowerCase().replace(/ё/g, "е").replace(/[^a-zа-я0-9]/g, " ");
    }

    // Простой стемминг: у слов длиннее 4 букв отрезаем 2 последние (но оставляем минимум 4),
    // дальше сравниваем как префикс слова: «смесителя» и «смесители» -> «смесите» ~ «смеситель».
    function stem(w) {
        return w.length > 4 ? w.slice(0, Math.max(4, w.length - 2)) : w;
    }

    function tokenize(query) {
        var words = normalize(query).split(/\s+/).filter(Boolean);
        var kept = words.filter(function (w) { return !STOP[w]; });
        if (!kept.length) { kept = words; }
        var seen = {}, out = [];
        kept.forEach(function (w) {
            var st = stem(w);
            if (!seen[st]) { seen[st] = 1; out.push(st); }
        });
        return out;
    }

    // Сколько слов поля начинаются с основы (0 — нет совпадения); поле уже нормализовано
    function countHits(norm, st) {
        var n = 0, from = 0, hay = " " + norm, needle = " " + st;
        while (true) {
            var i = hay.indexOf(needle, from);
            if (i < 0) { return n; }
            n++;
            from = i + needle.length;
        }
    }

    // Подготовка записи индекса: нормализованные поля считаем один раз
    function prepare(entry) {
        if (!entry._n) {
            entry._n = {
                title: normalize(entry.title),
                headings: normalize((entry.headings || []).join(" . ")),
                products: normalize((entry.products || []).join(" . ")),
                description: normalize(entry.description),
                text: normalize(entry.text)
            };
        }
        return entry._n;
    }

    function scoreEntry(entry, tokens, requireAll) {
        var n = prepare(entry), total = 0, matched = 0;
        tokens.forEach(function (st) {
            var s = 0;
            Object.keys(WEIGHTS).forEach(function (f) {
                var h = countHits(n[f], st);
                if (h) { s += WEIGHTS[f] * (f === "text" ? Math.min(h, 5) : 1); }
            });
            if (s) { matched++; total += s; }
        });
        if (!matched || (requireAll && matched < tokens.length)) { return 0; }
        // бонус за полное вхождение всей фразы запроса в заголовок
        var phrase = tokens.join(" ");
        if (tokens.length > 1 && n.title.indexOf(phrase) >= 0) { total += 15; }
        return total;
    }

    // search(index, query) -> {results: [{entry, score}], partial: bool, tokens: [...]}
    function search(index, query) {
        var tokens = tokenize(query);
        if (!tokens.length) { return {results: [], partial: false, tokens: []}; }
        function run(requireAll) {
            var res = [];
            index.forEach(function (e) {
                var sc = scoreEntry(e, tokens, requireAll);
                if (sc) { res.push({entry: e, score: sc}); }
            });
            // при равных баллах выше более короткий (точный) заголовок
            res.sort(function (a, b) { return b.score - a.score || a.entry.title.length - b.entry.title.length; });
            return res;
        }
        var partial = false, results = run(true);
        if (!results.length && tokens.length > 1) { results = run(false); partial = results.length > 0; }
        return {results: results.slice(0, MAX_RESULTS), partial: partial, tokens: tokens};
    }

    root.SiteSearch = {search: search, tokenize: tokenize, normalize: normalize};
    if (typeof module !== "undefined" && module.exports) { module.exports = root.SiteSearch; }

    // ---------- интерфейс (только в браузере) ----------
    if (typeof document === "undefined") { return; }

    function esc(s) {
        return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    // Подсветка слов, начинающихся с основ запроса, в исходном тексте
    function highlight(text, tokens) {
        var norm = normalize(text), ranges = [], re = /[a-zа-я0-9]+/g, m;
        while ((m = re.exec(norm))) {
            for (var i = 0; i < tokens.length; i++) {
                if (m[0].indexOf(tokens[i]) === 0) { ranges.push([m.index, m.index + m[0].length]); break; }
            }
        }
        var out = "", pos = 0;
        ranges.forEach(function (r) {
            out += esc(text.slice(pos, r[0])) + "<mark>" + esc(text.slice(r[0], r[1])) + "</mark>";
            pos = r[1];
        });
        return out + esc(text.slice(pos));
    }

    // Фрагмент текста вокруг первого совпадения
    function snippet(entry, tokens) {
        var text = entry.text || "", norm = normalize(text), first = -1, re = /[a-zа-я0-9]+/g, m;
        while ((m = re.exec(norm))) {
            if (tokens.some(function (t) { return m[0].indexOf(t) === 0; })) { first = m.index; break; }
        }
        if (first < 0) { return highlight(entry.description || "", tokens); }
        var start = Math.max(0, first - 60);
        if (start > 0) {
            var sp = text.indexOf(" ", start);
            if (sp >= 0 && sp < first) { start = sp + 1; }
        }
        var piece = text.slice(start, start + 200);
        return (start > 0 ? "… " : "") + highlight(piece, tokens) + (start + 200 < text.length ? " …" : "");
    }

    var app = document.getElementById("search-app");
    if (!app) { return; }
    var input = document.getElementById("search-input");
    var box = document.getElementById("search-results");
    var status = document.getElementById("search-status");
    var hints = document.getElementById("search-hints");
    var empty = document.getElementById("search-empty");
    var index = null;

    function render() {
        var q = input.value.trim();
        box.innerHTML = "";
        status.textContent = "";
        empty.hidden = true;
        hints.hidden = !!q;
        if (!q || !index) { return; }
        var r = search(index, q);
        if (!r.results.length) { empty.hidden = false; return; }
        if (r.partial) { status.textContent = "Частичное совпадение: нет страниц, где есть все слова запроса."; }
        box.innerHTML = r.results.map(function (x) {
            var e = x.entry;
            return "<li><a href=\"" + esc(e.url) + "\">" + highlight(e.title, r.tokens) + "</a>" +
                "<span class=\"search-section\">" + esc(e.section) + "</span>" +
                "<p>" + snippet(e, r.tokens) + "</p></li>";
        }).join("");
    }

    function syncUrl() {
        var q = input.value.trim();
        try { history.replaceState(null, "", q ? "?q=" + encodeURIComponent(q) : location.pathname); } catch (e) { /* file:// и т. п. */ }
    }

    input.value = new URLSearchParams(location.search).get("q") || "";
    input.addEventListener("input", function () { syncUrl(); render(); });
    app.querySelector("form").addEventListener("submit", function (e) { e.preventDefault(); syncUrl(); render(); });

    fetch(app.getAttribute("data-index")).then(function (r) { return r.json(); }).then(function (d) {
        index = d;
        render();
    }).catch(function () {
        status.textContent = "Не удалось загрузить поиск. Откройте разделы сайта через меню.";
    });
    render();
})(typeof window !== "undefined" ? window : globalThis);
