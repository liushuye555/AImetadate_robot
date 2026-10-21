#pragma once

#include <QString>
#include <QStringList>

namespace HiddenCommand {
int run(const QString &program, const QStringList &arguments, const QString &workingDirectory,
        int timeoutMs = 30000);
}
