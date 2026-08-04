public class Flow {
    public static int Leaf() {
        return 0;
    }

    public static int Bonus() {
        return 2;
    }

    public static int Middle() {
        return Leaf();
    }

    public static int Recurse(int n) {
        if (n <= 0) {
            return 0;
        }
        return Recurse(n - 1);
    }

    public static int Root() {
        Engine e = new Engine();
        return Middle() + Bonus() + Helper.Assist() + e.Run();
    }
}
