public class Core {
    static int Middle() {
        return 1;
    }

    static int Entry() {
        return Middle() + Helper.Assist();
    }

    int Handle() {
        return 2;
    }

    int Run() {
        return this.Handle();
    }
}
