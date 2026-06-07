/* Interactive quiz with answer tracking (spec §15). */
window.OpenLM = window.OpenLM || {};
(function (O) {
  O.quiz = {
    // items: [{question, options:[...], answer_index, explanation, concept}]
    render(container, items, notebookId) {
      container.innerHTML = "";
      items.forEach((q, qi) => {
        const card = document.createElement("div");
        card.className = "quiz-q";
        const qt = document.createElement("div");
        qt.className = "q-text";
        qt.textContent = (qi + 1) + ". " + (q.question || "");
        card.appendChild(qt);

        const opts = q.options || [];
        let answered = false;
        const buttons = [];
        opts.forEach((opt, oi) => {
          const b = document.createElement("button");
          b.className = "quiz-opt";
          b.textContent = opt;
          b.onclick = () => {
            if (answered) return;
            answered = true;
            const correct = oi === q.answer_index;
            b.classList.add(correct ? "correct" : "wrong");
            if (!correct && buttons[q.answer_index]) buttons[q.answer_index].classList.add("correct");
            const ex = document.createElement("div");
            ex.className = "quiz-explain";
            ex.textContent = (correct ? "✅ Correct! " : "❌ Incorrect. ") + (q.explanation || "");
            card.appendChild(ex);
            O.call("record_quiz", notebookId, q.question,
              opts[q.answer_index] || "", opt, correct, q.concept || "").catch(() => {});
          };
          buttons.push(b);
          card.appendChild(b);
        });
        container.appendChild(card);
      });
    },

    // Try to parse a ```json quiz block out of model markdown.
    parse(text) {
      const m = (text || "").match(/```json\s*([\s\S]*?)```/);
      const raw = m ? m[1] : text;
      try {
        const data = JSON.parse(raw);
        if (Array.isArray(data) && data.length && data[0].question) return data;
      } catch (e) { /* not json */ }
      return null;
    },
  };
})(window.OpenLM);
