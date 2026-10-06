import AppKit
import Sparkle
import Foundation
@main struct UpdateLifecycleHarness {
 @MainActor static func main() {
  let c=UpdateCoordinator(currentVersion:"1.6.1")
  let selectors=["supportsGentleScheduledUpdateReminders","updater:didAbortWithError:","updater:didFindValidUpdate:","updater:shouldPostponeRelaunchForUpdate:untilInvokingBlock:","updater:userDidMakeChoice:forUpdate:state:","standardUserDriverShouldHandleShowingScheduledUpdate:andInImmediateFocus:","standardUserDriverWillHandleShowingUpdate:forUpdate:state:","standardUserDriverDidReceiveUserAttentionForUpdate:","standardUserDriverWillFinishUpdateSession","updaterWillRelaunchApplication:"]
  for name in selectors {guard c.responds(to:NSSelectorFromString(name)) else {print("MISSING_SELECTOR",name);exit(1)}}
  guard c.value(forKey:"supportsGentleScheduledUpdateReminders") as? Bool==true else {print("gentle property not true");exit(1)}
  let controller=SPUStandardUpdaterController(startingUpdater:false,updaterDelegate:nil,userDriverDelegate:nil)
  c.model.apply(.updateFound(version:"1.6.2"))
  c.perform(NSSelectorFromString("updater:didAbortWithError:"),with:controller.updater,with:NSError(domain:SUSparkleErrorDomain,code:1001,userInfo:[SPUNoUpdateFoundReasonKey:NSNumber(value:SPUNoUpdateFoundReason.onLatestVersion.rawValue)]))
  RunLoop.main.run(until:Date().addingTimeInterval(0.1))
  guard c.state.availability == .upToDate else {print("NO_UPDATE_MISCLASSIFIED",c.state);exit(1)}
  c.perform(NSSelectorFromString("updater:didAbortWithError:"),with:controller.updater,with:NSError(domain:SUSparkleErrorDomain,code:1002))
  RunLoop.main.run(until:Date().addingTimeInterval(0.1))
  guard c.state.availability == .failed else {print("REAL_ERROR_NOT_FAILED",c.state);exit(1)}
  let consent=UpdateInstallConsent()
  assert(!consent.consume())
  for choice in [UserUpdateChoice.later,.skip,.cancel] {consent.record(choice);assert(!consent.consume())}
  consent.record(.install);assert(consent.consume());assert(!consent.consume())
  consent.record(.install);consent.reset();assert(!consent.consume())
  assert(!BackendSupervisor.reportsSuccess(["success":false],transportOK:true))
  assert(!BackendSupervisor.reportsSuccess(["success":true],transportOK:false))
  assert(!BackendSupervisor.reportsSuccess(nil,transportOK:true))
  assert(BackendSupervisor.reportsSuccess(["success":true],transportOK:true))
  let address="628A1160-0E76-D5A7-CCB6-5DA73EC96391"
  assert(PendingReconnectStore.connectedAddress(in:["connected":false,"device_address":address])==nil)
  assert(PendingReconnectStore.connectedAddress(in:["connected":true,"device_address":address])==address)
  assert(PendingReconnectStore.connectedAddress(in:nil)==nil)
  assert(PendingReconnectStore.connectedAddress(in:["connected":true,"device_address":"a"])==nil)
  let item=SUAppcastItem(dictionary:["sparkle:version":"8","enclosure":["url":"http://127.0.0.1/fixture.zip","sparkle:version":"8","length":"1"]])!
  var held:(()->Void)?
  var installed=0
  var abandoned=0
  c.onRelaunchPreparing={target,done in assert(target=="8");held=done}
  c.onRelaunchAbandoned={abandoned += 1}
  assert(c.updater(controller.updater,shouldPostponeRelaunchForUpdate:item,untilInvokingBlock:{installed += 1}))
  RunLoop.main.run(until:Date().addingTimeInterval(0.08))
  assert(c.isRelaunchImminent && c.pendingTargetBuild=="8")
  c.updater(controller.updater,didAbortWithError:NSError(domain:SUSparkleErrorDomain,code:1002))
  RunLoop.main.run(until:Date().addingTimeInterval(0.08))
  assert(!c.isRelaunchImminent && abandoned==1)
  held?();assert(installed==0,"Cancelled preparation must not install")
  let slow=UpdateCoordinator(currentVersion:"1.6.1",relaunchPreparationDeadline:0.05)
  var timeoutInstalls=0
  var late:(()->Void)?
  slow.onRelaunchPreparing={_,done in late=done}
  _=slow.updater(controller.updater,shouldPostponeRelaunchForUpdate:item,untilInvokingBlock:{timeoutInstalls += 1})
  RunLoop.main.run(until:Date().addingTimeInterval(0.12))
  assert(timeoutInstalls==1 && slow.isRelaunchImminent)
  late?();assert(timeoutInstalls==1)
  print("ALL_SELECTORS_EXPORTED",selectors.count,"NO_UPDATE_AND_FAILURE_DISTINCT CONSENT_ONE_SHOT CONNECTED_ONLY PREPARATION_CANCEL_TIMEOUT")
 }
}
