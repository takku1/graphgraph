const { Assist } = require('./helper');

function Leaf() {
  return 0;
}

function Bonus() {
  return 2;
}

function Middle() {
  return Leaf();
}

class Engine {
  Run() {
    return Leaf();
  }
}

function Recurse(n) {
  if (n <= 0) return 0;
  return Recurse(n - 1);
}

function Root() {
  const e = new Engine();
  return Middle() + Bonus() + Assist() + e.Run();
}

module.exports = { Root, Middle, Leaf, Bonus, Recurse, Engine };
