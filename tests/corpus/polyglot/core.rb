require_relative 'helper'

def Middle
  1
end

def Entry
  Middle() + Assist()
end

class Service
  def Handle
    2
  end

  def Run
    Handle()
  end
end
