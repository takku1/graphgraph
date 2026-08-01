mod helper;

pub fn middle() -> i32 {
    1
}

pub fn entry() -> i32 {
    middle() + helper::assist()
}

pub struct Service;

impl Service {
    pub fn handle(&self) -> i32 {
        2
    }

    pub fn run(&self) -> i32 {
        self.handle()
    }
}
