// The trio picker on the home page: choose three classes and be taken to the page for that trio, or told it is coming soon.

const WANTED = 3;

export function initPicker(doc) {
  const picker = doc.getElementById("picker");
  const status = doc.getElementById("picker-status");
  if (!picker || !status) return;
  const boxes = [...picker.querySelectorAll('input[type="checkbox"]')];
  const live = new Set((picker.dataset.live ?? "").split(" ").filter(Boolean));
  const nameOf = (box) => doc.querySelector('label[for="' + box.id + '"]').textContent.trim();

  const update = () => {
    const chosen = boxes.filter((box) => box.checked);
    for (const box of boxes) box.disabled = !box.checked && chosen.length >= WANTED;
    status.replaceChildren();
    if (chosen.length < WANTED) {
      const more = WANTED - chosen.length;
      status.append(doc.createTextNode(more === WANTED ? "Pick three classes." : "Pick " + more + " more class" + (more === 1 ? "." : "es.")));
      return;
    }
    // the boxes are in class-id order, which is the order of a trio's address and name
    const slug = chosen.map((box) => box.value.toLowerCase()).join("-");
    const name = chosen.map(nameOf).join(" / ");
    if (live.has(slug)) {
      const link = doc.createElement("a");
      link.setAttribute("href", "/trio/" + slug + "/");
      link.textContent = "Open " + name + ": best gear";
      status.append(link);
    } else {
      status.append(doc.createTextNode(name + ": coming soon."));
    }
  };

  for (const box of boxes) box.addEventListener("change", update);
  picker.hidden = false;
  update();
}
