package corpus

func Middle() int {
	return 1
}

func Entry() int {
	return Middle() + Assist()
}

type Service struct{}

func (s Service) Handle() int {
	return 2
}

func (s Service) Run() int {
	return s.Handle()
}
