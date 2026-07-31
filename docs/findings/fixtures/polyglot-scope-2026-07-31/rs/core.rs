mod helper;
use helper::Assist;

pub fn Leaf() -> i32 {
    0
}

pub fn Bonus() -> i32 {
    2
}

pub fn Middle() -> i32 {
    Leaf()
}

pub struct Engine;

impl Engine {
    pub fn Run(&self) -> i32 {
        Leaf()
    }
}

pub fn Recurse(n: i32) -> i32 {
    if n <= 0 {
        return 0;
    }
    Recurse(n - 1)
}

pub fn Root() -> i32 {
    let e = Engine;
    Middle() + Bonus() + Assist() + e.Run()
}
