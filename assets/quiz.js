// Reusable retrieval quiz. Usage:
//   <div class="quiz" id="q"></div>
//   <script src="../assets/quiz.js"></script>
//   <script>Quiz.mount(document.getElementById("q"), [{q, options: [...], answer: 2, why}]);</script>
// Immediate feedback per question; a running score at the bottom.
(function () {
  const css = `
  .quiz ol { padding-left: 1.2rem; }
  .quiz li.question { margin: 0 0 1.6rem; }
  .quiz .opts { display: grid; gap: .35rem; margin-top: .5rem; }
  .quiz button { font: inherit; font-size: .92rem; text-align: left; cursor: pointer;
    background: var(--card); color: var(--ink); border: 1px solid var(--rule);
    border-radius: 5px; padding: .45rem .7rem; }
  .quiz button:hover:not(:disabled) { border-color: var(--ink); }
  .quiz button.right { border-color: var(--ok); color: var(--ok); }
  .quiz button.wrong { border-color: var(--bad); color: var(--bad); text-decoration: line-through; }
  .quiz .why { font-size: .88rem; margin-top: .5rem; display: none; }
  .quiz .why.show { display: block; }
  .quiz .score { font-style: italic; color: var(--muted); }`;
  const style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  function mount(root, questions) {
    let answered = 0, correct = 0;
    const list = document.createElement("ol");
    const score = document.createElement("p");
    score.className = "score";
    const update = () => { score.textContent = `${correct} of ${answered} right so far (${questions.length} questions).`; };

    questions.forEach((item) => {
      const li = document.createElement("li");
      li.className = "question";
      li.innerHTML = `<div>${item.q}</div>`;
      const opts = document.createElement("div");
      opts.className = "opts";
      const why = document.createElement("div");
      why.className = "why";
      item.options.forEach((text, i) => {
        const b = document.createElement("button");
        b.type = "button";
        b.innerHTML = text;
        b.onclick = () => {
          const first = !li.dataset.done;
          if (i === item.answer) {
            b.classList.add("right");
            opts.querySelectorAll("button").forEach((x) => (x.disabled = true));
            why.innerHTML = "<strong>Yes.</strong> " + item.why;
            if (first) correct++;
          } else {
            b.classList.add("wrong");
            b.disabled = true;
            why.innerHTML = "Not that one. Try again.";
          }
          why.classList.add("show");
          if (first) { answered++; li.dataset.done = "1"; update(); }
        };
        opts.appendChild(b);
      });
      li.append(opts, why);
      list.appendChild(li);
    });
    root.append(list, score);
    update();
  }
  window.Quiz = { mount };
})();
