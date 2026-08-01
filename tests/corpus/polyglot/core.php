<?php
require_once 'helper.php';

function Middle() {
    return 1;
}

function Entry() {
    return Middle() + Assist();
}

class Other {
    function Handle() {
        return 9;
    }
}

class Service {
    function Handle() {
        return 2;
    }

    function Run() {
        return $this->Handle();
    }

    // Precision guard: `$other` is not a self-alias and has no declared type,
    // so this must NOT bind to the enclosing Service::Handle.
    function RunOther($other) {
        return $other->Handle();
    }
}
