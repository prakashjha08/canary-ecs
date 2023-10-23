import boto3
from time import sleep

##Update primary service with new Image from canary

def update_primary_service_td(region,cluster,canary_service,primary_service):
    session = boto3.session.Session(region_name = region)
    ecs = session.client('ecs')
    waiter = ecs.get_waiter('services_stable')


    canary_task_definition = ecs.describe_services(
        cluster = cluster,
        services = [
            canary_service,
        ]
    )

    primary_service_task_definition = ecs.describe_services(
        cluster = cluster,
        services = [
            primary_service,
        ]
    )

    primary_task_definition_update = ecs.update_service(
        cluster = cluster,
        service = primary_service,
        taskDefinition = canary_task_definition['services'][0]['taskDefinition'],
        forceNewDeployment = True
    )

    try:

        waiter.wait(
        cluster = cluster,
        services = [
            primary_service,
        ],
        WaiterConfig={
            'Delay': 15,
            'MaxAttempts': 20
        }
        )
        rollback = False
        print(f"Updated primary service with image {primary_task_definition_update['service']['taskDefinition']}")

    except Exception as e:
        rollback = True
    
    if rollback:
        primary_task_definition_update = ecs.update_service(
        cluster = cluster,
        service = primary_service,
        taskDefinition = primary_service_task_definition['services'][0]['taskDefinition'],
        forceNewDeployment = True
        )

        print(f"Primary service is still using Task definition {primary_service_task_definition['services'][0]['taskDefinition']}")

    return rollback

##Update ALB weight to 100 for primary

def alb_weight_updation(region,rule_arns,primary_tg,canary_tg):

    session = boto3.session.Session(region_name = region)
    elb = session.client('elbv2')

    j = 5

    while j < 101:
        for i in rule_arns:
            elb.modify_rule(
                    RuleArn = i,
                    Actions = [
                        {
                            'Type': 'forward',
                            'ForwardConfig': {
                                'TargetGroups': [
                                {
                                    'TargetGroupArn': primary_tg,
                                    'Weight': j
                                },
                                {
                                    'TargetGroupArn': canary_tg,
                                    'Weight': 100 - j
                                },
                            ],
                        }
                    }
                ]
            )
            sleep(1)
            print("waiting for 10s")
            print(f"Traffic moved by {j}% to primary tg - {primary_tg.split('/')[1]} on rule {i}")

        j += 5

    print(f"Successfully moved all traffic to Primary TG {primary_tg.split('/')[1]}")
        

##Update desired,max and min capacity to 0 for canary service

def ch_canary_capacity(region,cluster,canary_service):
    session = boto3.session.Session(region_name = region)
    ecs_auto_scaling = session.client('application-autoscaling')
    ecs = session.client('ecs')

    canary_service_details = ecs.describe_services(
        cluster = cluster,
        services = [
            canary_service
        ],
    )

    ecs.update_service(
        cluster = cluster,
        service = canary_service,
        forceNewDeployment = True,
        desiredCount=2
    )

    ecs_auto_scaling.register_scalable_target(
        ServiceNamespace='ecs',
        ResourceId=(canary_service_details['services'][0]['serviceArn']).split(':')[5],
        ScalableDimension='ecs:service:DesiredCount',
        MinCapacity=2,
        MaxCapacity=2,
    )
