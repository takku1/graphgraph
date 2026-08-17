import { Account } from './user';

export function persist(account: Account): number {
  return account.save();
}
