import boto3
from math import ceil
from canary_to_primary import alb_weight_updation, update_primary_service_td, ch_canary_capacity


##Inputs from Jenkins

region = 'ap-south-1'
cluster_name = 'spring3'
canary_service = "canary_tomcat"
primary_service = "tomcat"
percent_increase = 100
wish_to_switch_to_primary = False

session = boto3.session.Session(region_name=region)

elb = session.client('elbv2')
ecs = session.client('ecs')
ecs_auto_scaling = session.client('application-autoscaling')
sts = session.client('sts')
id = sts.get_caller_identity()

lb = elb.describe_load_balancers()


##Cluster ARN
cluster = 'arn:aws:ecs:{}:{}:cluster/{}'.format(region,id['Account'],cluster_name)

###Function to update canary service
def primary_ecs(*args):
    global primary_service
    primary_service_details = ecs.describe_services(
        cluster = args[2],
        services=[
            primary_service
        ],
    )
    primary_service_scalable_targets = ecs_auto_scaling.describe_scalable_targets(
        ServiceNamespace = 'ecs',
        ResourceIds = [
            (primary_service_details['services'][0]['serviceArn']).split(':')[5]
        ]
    )
    primary_service_desired = int(primary_service_details['services'][0]['desiredCount'])
    primary_service_max = int(primary_service_scalable_targets['ScalableTargets'][0]['MaxCapacity'])

    primary_tg = primary_service_details['services'][0]['loadBalancers'][0]['targetGroupArn']

    canary_desired = int(ceil((args[1] / 100) * primary_service_desired))
    canary_min = canary_desired
    canary_max = int(ceil((args[1] / 100) * primary_service_max) * 3)

    ###Update Canary service

    ecs.update_service(
        cluster = args[2],
        service=args[0],
        desiredCount=canary_desired
    )

    canary_resource_id = ((primary_service_details['services'][0]['serviceArn']).split(':')[5]).split('/')
    canary_resource_id[2] = args[0]


    ecs_auto_scaling.register_scalable_target(
        ServiceNamespace='ecs',
        ResourceId='/'.join(canary_resource_id),
        ScalableDimension='ecs:service:DesiredCount',
        MinCapacity=canary_min,
        MaxCapacity=canary_max,
    )

    canary_service_details = ecs.describe_services(
        cluster = args[2],
        services=[
            args[0]
        ],
    )
    canary_tg_arn = canary_service_details['services'][0]['loadBalancers'][0]['targetGroupArn']
    
    return canary_tg_arn, primary_tg

canary_tg, primary_tg = primary_ecs(canary_service, percent_increase,cluster)



###Function to update TGs associated with Canary ECS service
def tg_update(*args):
    listener_arns = []
    listener_primary_service = elb.describe_target_groups(
    TargetGroupArns = [args[1]]
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
            if any(args[0].split('/',2)[1] in string for string in [str(z) for y in (x.values() for x in rule['Actions'][0]['ForwardConfig']['TargetGroups']) for z in y]):
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
                                'TargetGroupArn': args[1],
                                'Weight': 100 - percent_increase
                            },
                            {
                                'TargetGroupArn': args[0],
                                'Weight': percent_increase
                            },
                        ],
                        }
                    }
                ]
            )

    return rule_arns

rule_arns = tg_update(canary_tg, primary_tg)


if percent_increase == 100 and wish_to_switch_to_primary == True:
    update_primary_service_td(region,cluster,canary_service,primary_service)
    alb_weight_updation(region,rule_arns,primary_tg,canary_tg)
    ch_canary_capacity(region,rule_arns,primary_tg,canary_tg)
else:
    print(f"Traffic to be passed to canary is {percent_increase}%")
