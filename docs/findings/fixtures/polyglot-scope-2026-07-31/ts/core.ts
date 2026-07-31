import { Assist } from './helper';

export function Leaf(): number {
  return 0;
}

export function Bonus(): number {
  return 2;
}

export function Middle(): number {
  return Leaf();
}

export class Engine {
  Run(): number {
    return Leaf();
  }
}

export function Recurse(n: number): number {
  if (n <= 0) return 0;
  return Recurse(n - 1);
}

export function Root(): number {
  const e = new Engine();
  return Middle() + Bonus() + Assist() + e.Run();
}
