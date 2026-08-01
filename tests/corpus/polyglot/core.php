<?php
require_once 'helper.php';

function Middle() {
    return 1;
}

function Entry() {
    return Middle() + Assist();
}

class Service {
    function Handle() {
        return 2;
    }

    function Run() {
        return $this->Handle();
    }
}
