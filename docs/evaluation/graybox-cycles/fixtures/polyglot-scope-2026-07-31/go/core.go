package main

func Leaf() int {
	return 0
}

func Bonus() int {
	return 2
}

func CoreMiddle() int {
	return Leaf()
}

type Engine struct{}

func (e Engine) Run() int {
	return Leaf()
}

func Recurse(n int) int {
	if n <= 0 {
		return 0
	}
	return Recurse(n - 1)
}

func Root() int {
	e := Engine{}
	return CoreMiddle() + Bonus() + Assist() + e.Run()
}
