function Support() {
  return 1;
}

function Assist() {
  return Support();
}

function Middle() {
  return 99;
}

module.exports = { Assist, Support, Middle };
