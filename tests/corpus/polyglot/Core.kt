package corpus

fun Middle(): Int {
    return 1
}

fun Entry(): Int {
    return Middle() + Assist()
}

class Service {
    fun Handle(): Int {
        return 2
    }

    fun Run(): Int {
        return Handle()
    }
}
