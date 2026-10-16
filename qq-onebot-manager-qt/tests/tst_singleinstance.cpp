#include <QLocalSocket>
#include <QSignalSpy>
#include <QUuid>
#include <QtTest>

#include "app/SingleInstance.h"

class TestSingleInstance : public QObject {
    Q_OBJECT
private:
    static QString endpoint() {
        return "qq-manager-ipc-test-" + QUuid::createUuid().toString(QUuid::Id128);
    }

private slots:
    void showActionRequestsWindowActivation() {
        const QString name = endpoint();
        SingleInstance primary(name);
        QVERIFY(primary.tryLock());
        QSignalSpy activation(&primary, &SingleInstance::anotherInstanceRequested);
        QVERIFY(activation.isValid());

        // tryLock waits for the local socket exchange; process server events after it returns.
        SingleInstance secondary(name);
        QVERIFY(!secondary.tryLock("show"));
        QTRY_COMPARE(activation.size(), 1);
    }

    void stopAndRestartActionsAreForwardedExactly() {
        const QString name = endpoint();
        SingleInstance primary(name);
        QVERIFY(primary.tryLock());
        QSignalSpy commands(&primary, &SingleInstance::commandRequested);
        QVERIFY(commands.isValid());

        const QStringList actions = {"stop-services", "restart-services"};
        for (qsizetype i = 0; i < actions.size(); ++i) {
            SingleInstance secondary(name);
            QVERIFY(!secondary.tryLock(actions.at(i)));
            QTRY_COMPARE(commands.size(), i + 1);
            QCOMPARE(commands.at(i).at(0).toString(), actions.at(i));
        }
    }

    void oneClientRequestIsDispatchedOnlyOnce() {
        const QString name = endpoint();
        SingleInstance primary(name);
        QVERIFY(primary.tryLock());
        QSignalSpy activation(&primary, &SingleInstance::anotherInstanceRequested);
        QVERIFY(activation.isValid());

        SingleInstance secondary(name);
        QVERIFY(!secondary.tryLock("show"));
        QTRY_COMPARE(activation.size(), 1);
        QTest::qWait(50);
        QCOMPARE(activation.size(), 1);
    }

    void incompleteClientDisconnectDoesNotDispatchTwice() {
        const QString name = endpoint();
        SingleInstance primary(name);
        QVERIFY(primary.tryLock());
        QSignalSpy activation(&primary, &SingleInstance::anotherInstanceRequested);
        QVERIFY(activation.isValid());

        QLocalSocket incomplete;
        incomplete.connectToServer(name);
        QVERIFY(incomplete.waitForConnected(1000));
        incomplete.disconnectFromServer();

        // Let both the disconnect callback and the one-second incomplete-client timeout run.
        QTest::qWait(1200);
        QCOMPARE(activation.size(), 1);
    }
};

QTEST_GUILESS_MAIN(TestSingleInstance)
#include "tst_singleinstance.moc"
