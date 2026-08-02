#pragma once
#include <QString>

class Strings {
public:
    static QString get(const QString &key, const QString &lang);
    static QString zh(const QString &key);
    static QString en(const QString &key);
    static QString section(const QString &section);
};
