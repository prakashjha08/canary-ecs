import boto3
import math


##Inputs from Jenkins

region = 'ap-south-1'
cluster_name = 'spring3'
canary_service = "canary_tomcat"
percent_increase = 10

##Cluster ARN


session = boto3.session.Session(region_name=region)

elb = session.client('elbv2')
ecs = session.client('ecs')
ecs_auto_scaling = session.client('application-autoscaling')
sts = session.client('sts')
id = sts.get_caller_identity()

cluster = 'arn:aws:ecs:{}:{}:cluster/{}'.format(region,id['Account'],cluster_name)

primary_service = canary_service.split('_',1)
primary_service_details = ecs.describe_services(
    cluster = cluster,
    services=[
        primary_service[1]
    ],
)
primary_service_scalable_targets = ecs_auto_scaling.describe_scalable_targets(
    ServiceNamespace = 'ecs',
    ResourceIds = [
        (primary_service_details['services'][0]['serviceArn']).split(':')[5]
    ]
)
primary_service_desired = int(primary_service_details['services'][0]['desiredCount'])
primary_service_min = int(primary_service_scalable_targets['ScalableTargets'][0]['MinCapacity'])
primary_service_max = int(primary_service_scalable_targets['ScalableTargets'][0]['MaxCapacity'])


tg_primary_service = primary_service_details['services'][0]['loadBalancers'][0]['targetGroupArn']

###Canary updating
canary_desired = int(math.ceil((percent_increase / 100) * primary_service_desired))

canary_min = canary_desired
canary_max = int(math.ceil((percent_increase / 100) * primary_service_max))

###Update Canary service

update_canary_service = ecs.update_service(
    cluster=cluster,
    service=canary_service,
    desiredCount=canary_desired
)

canary_resource_id = ((primary_service_details['services'][0]['serviceArn']).split(':')[5]).split('/')
canary_resource_id[2] = canary_service


update_min_max_capacity = ecs_auto_scaling.register_scalable_target(
    ServiceNamespace='ecs',
    ResourceId='/'.join(canary_resource_id),
    ScalableDimension='ecs:service:DesiredCount',
    MinCapacity=canary_min,
    MaxCapacity=canary_max,
)
###Working till here###

canary_service_details = ecs.describe_services(
    cluster = cluster,
    services=[
        canary_service
    ],
)

canary_tg_arn = canary_service_details['services'][0]['loadBalancers'][0]['targetGroupArn']
canary_tg = canary_tg_arn.split('/',2)[1]

lb_arns = []
listener_arns = []
lb = elb.describe_load_balancers()



listener_primary_service = elb.describe_target_groups(
    TargetGroupArns = [tg_primary_service]
)


listener = elb.describe_listeners(
    LoadBalancerArn = listener_primary_service['TargetGroups'][0]['LoadBalancerArns'][0]
)

for j in listener['Listeners']:
    listener_arns.append(j['ListenerArn'])


rule_arns = []
for i in listener_arns:
    rules = elb.describe_rules(
        ListenerArn = i
    )

    for rule in rules['Rules']:
        if any(canary_tg in string for string in [str(z) for y in (x.values() for x in rule['Actions'][0]['ForwardConfig']['TargetGroups']) for z in y]):
            rule_arns.append(rule['RuleArn'])

for i in rule_arns:
    response = elb.modify_rule(
            RuleArn=i,
            
            Actions=[
                {
                    'Type': 'forward',
                    'ForwardConfig': {
                        'TargetGroups': [
                        {
                            'TargetGroupArn': tg_primary_service,
                            'Weight': 100 - percent_increase
                        },
                        {
                            'TargetGroupArn': canary_tg_arn,
                            'Weight': percent_increase
                        },
                    ],
                    }
                }
            ]
        )
