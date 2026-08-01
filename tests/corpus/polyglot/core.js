const { Assist } = require('./helper');

function Middle() {
  return 1;
}

function Entry() {
  return Middle() + Assist();
}

class Service {
  Handle() {
    return 2;
  }

  Run() {
    return this.Handle();
  }
}

module.exports = { Entry, Middle, Service };
