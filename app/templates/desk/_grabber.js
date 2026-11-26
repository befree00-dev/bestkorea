/* BestKorea 가져오기 버튼(북마클릿). Reddit·YouTube·X 게시물 페이지에서 실행되어 데이터를 읽고,
   BestKorea 가져오기 창으로 넘긴다. 줄바꿈을 지워 한 줄로 만들므로 // 주석은 쓰지 않는다. */
(function () {
  var O = {{ origin|tojson }};
  var N = {{ cfg.COMMENTS_PER_ITEM|int }};
  var h = location.hostname, site = null;
  if (/(^|\.)reddit\.com$/.test(h)) { site = "reddit"; }
  else if (/(^|\.)youtube\.com$/.test(h)) { site = "youtube"; }
  else if (/(^|\.)(x|twitter)\.com$/.test(h)) { site = "x"; }
  if (!site) { alert("BestKorea: Reddit, YouTube, X 게시물 페이지에서 눌러 주세요."); return; }
  if (window.__bestkoreaBusy) { alert("BestKorea: 이미 가져오는 중입니다."); return; }

  var w = window.open(O + "/desk/import?from=bookmarklet", "bestkorea_import");
  var payload = null, ready = false, sent = false, box = null;
  window.__bestkoreaBusy = true;

  function status(text, copyText) {
    if (!box) {
      box = document.createElement("div");
      box.style.cssText = "position:fixed;top:16px;right:16px;z-index:2147483647;max-width:340px;padding:14px 16px;" +
        "background:#1f4fd8;color:#fff;font:14px/1.5 -apple-system,sans-serif;border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.3)";
      document.body.appendChild(box);
    }
    box.textContent = "BestKorea: " + text;
    if (copyText) {
      var b = document.createElement("button");
      b.textContent = "데이터 복사";
      b.style.cssText = "display:block;margin-top:10px;padding:6px 12px;border:0;border-radius:6px;background:#fff;color:#1f4fd8;font-weight:700;cursor:pointer";
      b.onclick = function () {
        navigator.clipboard.writeText(copyText).then(function () { b.textContent = "복사됨 - BestKorea 가져오기 칸에 붙여넣으세요"; });
      };
      box.appendChild(b);
    }
  }
  function finish() { window.__bestkoreaBusy = false; setTimeout(function () { if (box) { box.remove(); box = null; } }, 4000); }
  function fail(msg) { window.__bestkoreaBusy = false; if (box) { box.remove(); box = null; } alert("BestKorea: " + msg); if (w) { try { w.close(); } catch (e) {} } }
  function go() {
    if (payload && ready && !sent && w) {
      sent = true;
      w.postMessage({ type: "bestkorea-import", site: site, json: payload }, O);
      status("수집함으로 보냈습니다.");
      finish();
    }
  }
  function deliver(obj) {
    payload = typeof obj === "string" ? obj : JSON.stringify(obj);
    go();
    setTimeout(function () {
      if (!sent) {
        status("가져오기 창과 연결되지 않았습니다. 아래 버튼으로 복사한 뒤 BestKorea 가져오기 페이지에 붙여넣으세요.",
               JSON.stringify({ site: site, json: payload }));
        window.__bestkoreaBusy = false;
      }
    }, 6000);
  }
  window.addEventListener("message", function (e) {
    if (e.origin === O && e.data === "bestkorea-ready") { ready = true; go(); }
  });

  function num(s) {
    if (!s) { return 0; }
    var m = String(s).replace(/,/g, "").match(/(\d+(?:\.\d+)?)\s*([KMB천만억]?)/i);
    if (!m) { return 0; }
    var mul = { K: 1e3, M: 1e6, B: 1e9, "천": 1e3, "만": 1e4, "억": 1e8 }[(m[2] || "").toUpperCase()] || 1;
    return Math.round(parseFloat(m[1]) * mul);
  }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function text(el) { return el ? (el.innerText || el.textContent || "").trim() : ""; }

  /* ---------------- Reddit: 게시글 주소 + .json ---------------- */
  function grabReddit() {
    var m = location.pathname.match(/^\/r\/[^\/]+\/comments\/[a-z0-9]+/i);
    if (!m) { fail("Reddit 게시글 페이지에서 눌러 주세요."); return; }
    status("Reddit 글과 댓글을 읽는 중…");
    fetch(m[0] + "/.json?limit=100&depth=1&sort=top&raw_json=1", { credentials: "include" })
      .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.text(); })
      .then(deliver)
      .catch(function (e) { fail("Reddit 데이터를 가져오지 못했습니다 (" + e.message + ")"); });
  }

  /* ---------------- YouTube: 영상 정보 + 화면에 불러온 댓글 ---------------- */
  async function grabYouTube() {
    var vid = location.pathname === "/watch" ? new URLSearchParams(location.search).get("v") : null;
    if (!vid) { fail("YouTube 영상 페이지(youtube.com/watch?v=...)에서 눌러 주세요. 쇼츠는 지원하지 않습니다."); return; }
    var pr = null, player = document.getElementById("movie_player");
    try { if (player && player.getPlayerResponse) { pr = player.getPlayerResponse(); } } catch (e) {}
    if (!pr || !pr.videoDetails || pr.videoDetails.videoId !== vid) { pr = window.ytInitialPlayerResponse; }
    var vd = pr && pr.videoDetails && pr.videoDetails.videoId === vid ? pr.videoDetails : {};
    var mf = (pr && pr.microformat && pr.microformat.playerMicroformatRenderer) || {};
    var y0 = window.scrollY;
    status("댓글을 불러오는 중… (화면이 자동으로 내려갑니다)");
    var section = document.querySelector("ytd-comments#comments") || document.querySelector("ytd-comments");
    if (section) { section.scrollIntoView(); }
    var count = 0, t0 = Date.now(), last = -1, still = 0, stop = "timeout";
    while (Date.now() - t0 < 45000) {
      await sleep(700);
      count = num(text(document.querySelector("ytd-comments-header-renderer #count")));
      var n = document.querySelectorAll("ytd-comment-thread-renderer").length;
      if (n >= N) { stop = "limit"; break; }
      if (n === last) { still += 1; if (still >= 8 && (n > 0 || Date.now() - t0 > 12000)) { stop = "idle"; break; } } else { still = 0; }
      last = n;
      status("댓글 " + n + "개 읽는 중… (화면이 자동으로 내려갑니다)");
      window.scrollTo(0, document.documentElement.scrollHeight);
    }
    var comments = [];
    document.querySelectorAll("ytd-comment-thread-renderer").forEach(function (t) {
      if (comments.length >= N) { return; }
      var body = text(t.querySelector("#content-text"));
      if (body) {
        comments.push({ author: text(t.querySelector("#author-text")), body: body,
                        score: num(text(t.querySelector("#vote-count-middle"))) });
      }
    });
    window.scrollTo(0, y0);
    deliver({
      id: vid,
      title: vd.title || text(document.querySelector("ytd-watch-metadata h1")) || document.title.replace(/ - YouTube$/, ""),
      text: vd.shortDescription || text(document.querySelector("#description-inline-expander")),
      author: vd.author || text(document.querySelector("ytd-channel-name a")),
      published: mf.publishDate || mf.uploadDate || "",
      num_comments: count, comments: comments, debug: { stop: stop, read: comments.length }
    });
  }

  /* ---------------- X: 게시물 + 화면에 불러온 답글 ---------------- */
  async function grabX() {
    var m = location.pathname.match(/^\/([A-Za-z0-9_]{1,15})\/status\/(\d+)/);
    if (!m) { fail("X 게시물 페이지(x.com/아이디/status/숫자)에서 눌러 주세요."); return; }
    var id = m[2];
    function idOf(a) {
      var link = a.querySelector("a[href*='/status/'] time");
      var href = link && link.parentElement ? link.parentElement.getAttribute("href") || "" : "";
      var mm = href.match(/\/status\/(\d+)/);
      return mm ? mm[1] : null;
    }
    function handleOf(a) { var mm = text(a.querySelector("[data-testid='User-Name']")).match(/@([A-Za-z0-9_]{1,15})/); return mm ? mm[1] : ""; }
    function metric(a, testid) {
      var el = a.querySelector("[data-testid='" + testid + "']") || a.querySelector("[data-testid='un" + testid + "']");
      return num(el ? el.getAttribute("aria-label") || text(el) : "");
    }
    status("게시물과 답글을 불러오는 중… (화면이 자동으로 내려갑니다)");
    var main = null, t0 = Date.now();
    while (!main && Date.now() - t0 < 8000) {
      document.querySelectorAll("article[data-testid='tweet']").forEach(function (a) { if (!main && idOf(a) === id) { main = a; } });
      if (!main) { await sleep(500); }
    }
    if (!main) { fail("게시물을 찾지 못했습니다. 페이지가 다 열린 뒤 다시 눌러 주세요."); return; }
    var textEl = main.querySelector("[data-testid='tweetText']");
    var img = main.querySelector("[data-testid='tweetPhoto'] img");
    var userText = text(main.querySelector("[data-testid='User-Name']"));
    var at = userText.indexOf("@" + (handleOf(main) || m[1]));
    var nameLine = (at > 0 ? userText.slice(0, at) : userText.split("\n")[0]).replace(/\s+/g, " ").trim();
    var time = main.querySelector("time");
    var data = {
      id: id, handle: handleOf(main) || m[1], name: nameLine, text: text(textEl),
      lang: textEl ? textEl.getAttribute("lang") || "" : "", image: img ? img.src : "",
      published: time ? time.getAttribute("datetime") : "", num_comments: metric(main, "reply"), comments: []
    };
    /* X 는 스크롤하면 화면 밖 게시물을 지우므로, 문서 안의 절대 위치로 '본문 아래'인지 판단한다 */
    function yOf(el) { return el.getBoundingClientRect().top + window.scrollY; }
    /* '답글 더 보기' 버튼과 '더 찾아보기' 같은 다른 섹션 제목 (X 화면 언어별) */
    var MORE = /(show (more|additional) repl|more replies|답글 더 보기|답글 더보기|더 많은 답글|추가 답글|返信をさらに表示|さらに返信|显示更多回复|顯示更多回覆|mostrar más respuestas|mostrar mais respostas|weitere antworten|afficher plus de réponses)/i;
    var DISCOVER = /(discover more|더 찾아보기|더 많은 게시물 보기|もっと見つける|发现更多|探索更多|descubre más|descubra mais|mehr entdecken|découvrir plus|en découvrir plus)/i;
    var mainY = yOf(main), endY = Infinity;
    var seen = {}, y0 = window.scrollY, last = 0, still = 0, clicked = 0, stop = "timeout";
    seen[id] = true;
    function collect() {
      document.querySelectorAll("div[data-testid='cellInnerDiv']").forEach(function (cell) {
        var y = yOf(cell);
        if (y <= mainY || y >= endY) { return; }
        var a = cell.querySelector("article[data-testid='tweet']");
        if (!a) {
          var h = cell.querySelector("h2");
          if (h && DISCOVER.test(text(h))) { endY = y; } /* 다른 섹션이 시작되면 거기까지만 */
          return;
        }
        var rid = idOf(a);
        if (!rid || seen[rid]) { return; }
        seen[rid] = true;
        var body = text(a.querySelector("[data-testid='tweetText']"));
        if (body) { data.comments.push({ author: "@" + handleOf(a), body: body, score: metric(a, "like"), y: y }); }
      });
      data.comments = data.comments.filter(function (c) { return c.y < endY; });
    }
    function clickMore() {
      var n = 0;
      document.querySelectorAll("div[data-testid='cellInnerDiv'] [role='button'], div[data-testid='cellInnerDiv'] button").forEach(function (btn) {
        if (btn.__bestkorea || btn.closest("article")) { return; }
        var y = yOf(btn);
        if (y > mainY && y < endY && MORE.test(text(btn))) { btn.__bestkorea = true; btn.click(); n += 1; }
      });
      return n;
    }
    t0 = Date.now();
    while (true) {
      collect();
      if (data.comments.length >= N * 2) { stop = "limit"; break; }
      if (Date.now() - t0 > 45000) { stop = "timeout"; break; }
      var pressed = clickMore();
      clicked += pressed;
      var atBottom = window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 10;
      var pastEnd = endY !== Infinity && window.scrollY + window.innerHeight >= endY;
      if (data.comments.length > last || pressed) { still = 0; }
      else if (atBottom || pastEnd) { still += 1; if (still >= 8) { stop = endY !== Infinity ? "section" : "idle"; break; } }
      last = data.comments.length;
      status("답글 " + data.comments.length + "개 읽는 중… (화면이 자동으로 내려갑니다)");
      if (!pastEnd) { window.scrollBy(0, window.innerHeight * 0.8); }
      await sleep(pressed ? 1500 : 700);
    }
    window.scrollTo(0, y0);
    data.comments.forEach(function (c) { delete c.y; });
    data.debug = { stop: stop, clicked: clicked, read: data.comments.length };
    deliver(data);
  }

  var run = { reddit: grabReddit, youtube: grabYouTube, x: grabX }[site];
  Promise.resolve(run()).catch(function (e) { fail("가져오는 중 오류가 났습니다 (" + e.message + ")"); });
})();
