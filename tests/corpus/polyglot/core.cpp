#include "helper.hpp"

int Middle() {
    return 1;
}

int Entry() {
    return Middle() + Assist();
}

class Service {
public:
    int Handle() {
        return 2;
    }

    int Run() {
        return this->Handle();
    }
};
