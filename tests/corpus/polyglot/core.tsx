import { Assist } from './helper';

export function Middle(): number {
  return 1;
}

export function Entry(): number {
  return Middle() + Assist();
}

export class Service {
  Handle(): number {
    return 2;
  }

  Run(): number {
    return this.Handle();
  }
}
