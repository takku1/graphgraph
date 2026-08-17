package heldout

func Persist(account Account) int {
	return account.Save()
}
