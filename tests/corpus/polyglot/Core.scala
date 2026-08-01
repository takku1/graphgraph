package corpus

object Core {
  def Middle(): Int = 1

  def Entry(): Int = Middle() + Helper.Assist()

  def Handle(): Int = 2

  def Run(): Int = Handle()
}
