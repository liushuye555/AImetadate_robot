#include "HiddenCommand.h"

#include <QProcess>
#include <QProcessEnvironment>
#ifdef Q_OS_WIN
#include <qt_windows.h>
#endif

int HiddenCommand::run(const QString &program, const QStringList &arguments,
                       const QString &workingDirectory, int timeoutMs)
{
    QProcess command;
    command.setProgram(program);
    command.setArguments(arguments);
    command.setWorkingDirectory(workingDirectory);
    auto environment = QProcessEnvironment::systemEnvironment();
    environment.insert(QStringLiteral("PYTHONUTF8"), QStringLiteral("1"));
    command.setProcessEnvironment(environment);
    command.setStandardInputFile(QProcess::nullDevice());
    command.setStandardOutputFile(QProcess::nullDevice());
    command.setStandardErrorFile(QProcess::nullDevice());
#ifdef Q_OS_WIN
    // uv's venv redirectors can be console executables even when named pythonw.
    // Hide by native creation flags, independently of the interpreter filename.
    command.setCreateProcessArgumentsModifier([](QProcess::CreateProcessArguments *args) {
        args->flags |= CREATE_NO_WINDOW;
        args->startupInfo->dwFlags |= STARTF_USESHOWWINDOW;
        args->startupInfo->wShowWindow = SW_HIDE;
    });
#endif
    command.start();
    if (!command.waitForStarted(5000))
        return 1;
    if (!command.waitForFinished(qMax(1, timeoutMs))) {
        command.kill();
        command.waitForFinished(5000);
        return 1;
    }
    return command.exitStatus() == QProcess::NormalExit ? command.exitCode() : 1;
}
