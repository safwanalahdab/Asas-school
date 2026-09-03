from rest_framework.throttling import UserRateThrottle


class MobileDeviceRegistrationThrottle(UserRateThrottle):
    scope = "mobile_device_registration"


class MobileDeviceUnregistrationThrottle(UserRateThrottle):
    scope = "mobile_device_unregistration"
