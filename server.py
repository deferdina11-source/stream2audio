<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {
    background:#0e0e0e;
    color:#fff;
    font-family:sans-serif;
    padding:20px;
}

input, button {
    width:100%;
    padding:12px;
    margin-top:10px;
    background:#1a1a1a;
    color:#fff;
    border:1px solid #333;
}

button {
    background:red;
    border:none;
}

.result {
    padding:10px;
    border-bottom:1px solid #333;
    cursor:pointer;
}

.progress {
    margin-top:20px;
}

.bar {
    height:6px;
    background:#333;
}

.bar-inner {
    height:6px;
    background:red;
    width:0%;
}
</style>
</head>

<body>

<input id="input" placeholder="Paste YouTube URL or search">

<div id="results"></div>

<div id="info"></div>

<button onclick="convert()">Convert</button>

<div class="progress" id="progress" style="display:none;">
    <div class="bar">
        <div class="bar-inner" id="bar"></div>
    </div>
    <div id="percent">0%</div>
</div>

<div id="download"></div>

<script>
let selectedUrl = null;
let timer;

// SEARCH
document.getElementById('input').addEventListener('input', () => {

    clearTimeout(timer);

    const value = input.value.trim();

    if (!value) return;

    if (value.includes("youtube")) {
        selectedUrl = value;
        results.innerHTML = '';
        return;
    }

    timer = setTimeout(async () => {

        const res = await fetch('/api/search', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({query:value})
        });

        const data = await res.json();

        results.innerHTML = '';

        data.forEach(v => {
            const div = document.createElement('div');
            div.className = 'result';
            div.textContent = v.title;

            div.onclick = () => {
                selectedUrl = v.webpage_url;
                input.value = v.title;
                results.innerHTML = '';
                loadInfo(selectedUrl);
            };

            results.appendChild(div);
        });

    }, 400);
});


// LOAD INFO
async function loadInfo(url) {
    const res = await fetch('/api/info', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({url})
    });

    const data = await res.json();

    document.getElementById('info').innerHTML = `
        <img src="${data.thumbnail}" width="100%">
        <p>${data.title}</p>
    `;
}


// CONVERT
async function convert() {

    const value = input.value.trim();

    if (!selectedUrl && !value.includes("youtube")) {
        alert("Select result or paste valid URL");
        return;
    }

    const url = selectedUrl || value;

    loadInfo(url);

    progress.style.display = 'block';

    let p = 0;

    const fake = setInterval(() => {
        p = Math.min(p + 10, 90);
        bar.style.width = p + '%';
        percent.textContent = p + '%';
    }, 300);

    const res = await fetch('/api/convert', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({url})
    });

    const data = await res.json();

    clearInterval(fake);

    bar.style.width = '100%';
    percent.textContent = '100%';

    download.innerHTML = `
        <a href="/api/download/${data.file_id}">
            <button>Download MP3</button>
        </a>
    `;
}
</script>

</body>
</html>
