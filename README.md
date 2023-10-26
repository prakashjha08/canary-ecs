# canary-ecs

What is a canary deployment?

A canary deployment is a progressive rollout of an application that splits traffic between an already-deployed version and a new version, rolling it out to a subset of users before rolling out fully.

------
Pre-requisites:
--------
1. 2 ECS services (service A, service B)
2. 2 TGs (TG-A, TG-B) associated with the above respective services
3. Weighted ALB rules that will divide the traffic between the TGs

--------

Script details:
-------------

canary.py - This python file contains the below functions:

* primary_ecs - This function fetches Primary service's details like minimum, desired and maimum capacity, sets canary container count and returns primary and canary target group details.

* tg_update - Based on the "percent_increase" argument, this function will update the canary and primary target groups percentage once the canary service becomes stable.


canary_to_primary.py - This file contains the below functions and it works only when percent_increase is 100 and value of wish_to_switch_to_primary is true:

* update_primary_service_td - It will fetch the canary task definition details and will update the Primary service task definition.

* alb_weight_updation - Once primary service becomes steady, traffic will be shifted to Primary by 5% at a time until canary traffic becomes 0.

* ch_canary_capacity - Traffic will be moved to primary and then canary count will be changed to min - 2, desired - 2 and max - 2

--------
How to switch traffic between primary and canary service?
-----------

To send some traffic to canary service:
```
python3 canary.py --region ap-south-1 --cluster_name preprod-cluster --canary_service cart-canary-service --primary_service cart-primary-service --percent_increase 10 --wish_to_switch_to_primary false
```

To send full traffic to canary and update task definition of primary service with the canary Image:
```
python3 canary.py --region ap-south-1 --cluster_name preprod-cluster --canary_service cart-canary-service --primary_service cart-primary-service --percent_increase 100 --wish_to_switch_to_primary true
```
